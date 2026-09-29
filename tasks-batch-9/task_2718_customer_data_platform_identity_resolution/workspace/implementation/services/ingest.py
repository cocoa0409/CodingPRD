"""Batch validation, the requeue loop and the four-phase identity resolution pass."""

import db
from errors import ApiError
from services import calc, cascade, derive

DETERMINISTIC_FIELD = {
    "EMAIL_NORM": "email_norm",
    "PHONE_NORM": "phone_norm",
    "LOYALTY_NUMBER": "loyalty_number",
}

RECEIVED_STATUS = "RECEIVED"


# --------------------------------------------------------- source quality

def source_batches(source_id):
    return [b for b in db.all_of("ingest_batches") if b["source_system_id"] == source_id]


def check_source_quarantine(source):
    """Hop one: cumulative evidence drives the feed to QUARANTINED. Hop two rejects
    every batch of that feed still sitting in RECEIVED."""
    if source["status"] not in ("REGISTERED", "ACTIVE"):
        return False
    if not derive.source_breaches_floor(source):
        return False
    source["status"] = "QUARANTINED"
    source["quarantine_count"] += 1
    for batch in db.by_seq(source_batches(source["id"])):
        if batch["status"] != RECEIVED_STATUS:
            continue
        batch["status"] = "REJECTED"
        batch["rejection_reason"] = "SOURCE_QUARANTINED"
        db.touch(batch)
    return True


# -------------------------------------------------------------- validation

def validate_batch(batch, source):
    evaluations = [calc.evaluate_record(record) for record in batch["records"]]
    quality = calc.batch_quality(evaluations, source["dq_scoring_mode"])
    batch["dq_score"] = quality["dq_score"]
    batch["valid_record_count"] = quality["valid_record_count"]
    batch["invalid_record_count"] = quality["invalid_record_count"]
    batch["dq_failure_breakdown"] = quality["dq_failure_breakdown"]
    batch["validated_at"] = db.now()
    floor = calc.dec(source["pii_completeness_floor"])
    batch["status"] = "VALIDATED" if quality["dq_score"] >= floor else "QUARANTINED"
    db.touch(batch)
    check_source_quarantine(source)
    db.touch(source)
    return batch


def requeue_batch(batch):
    if batch["retry_round"] >= calc.MAX_RETRY_ROUNDS:
        batch["status"] = "REJECTED"
        batch["rejection_reason"] = "RETRY_LIMIT_REACHED"
        db.touch(batch)
        raise ApiError("ERR_RETRY_LIMIT_REACHED")
    batch["status"] = RECEIVED_STATUS
    batch["retry_round"] += 1
    batch["dq_score"] = None
    batch["dq_failure_breakdown"] = {}
    batch["valid_record_count"] = 0
    batch["invalid_record_count"] = 0
    batch["validated_at"] = None
    db.touch(batch)
    return batch


# ---------------------------------------------------------------- promotion

IDENTIFIER_FIELDS = (
    "email_norm", "phone_norm", "first_name", "last_name",
    "postal_code", "address_hash", "loyalty_number",
)


def candidate_profiles():
    return db.by_seq(derive.segment_eligible_profiles())


def _enabled_rules(kind):
    rules = [
        r for r in db.all_of("match_rules")
        if r["status"] == "ENABLED" and r["rule_kind"] == kind
    ]
    rules.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rules


def _record_tier(record):
    tier = record.get("loyalty_tier")
    if isinstance(tier, str) and tier in calc.LOYALTY_ORDINAL:
        return tier
    return "NONE"


def _mint_profile(batch, source, record, evaluation):
    fields = {field: evaluation.get(field) for field in IDENTIFIER_FIELDS}
    profile = db.new_entity(
        "profiles",
        origin_batch_id=batch["id"],
        primary_source_system_id=source["id"],
        household_id=None,
        merged_into_profile_id=None,
        loyalty_tier=_record_tier(record),
        lifetime_value_cents=0,
        inferred_health_interest=record.get("inferred_health_interest"),
        inferred_ethnicity_affinity=record.get("inferred_ethnicity_affinity"),
        precise_geolocation_grid=record.get("precise_geolocation_grid"),
        resolution_status="UNRESOLVED",
        privacy_status="NORMAL",
        source_record_count=1,
        contributing_source_system_codes=[source["code"]],
        last_activity_at=record["event_timestamp"],
        **fields
    )
    return profile


def _attach_record(profile, source, record, evaluation):
    for field in IDENTIFIER_FIELDS:
        value = evaluation.get(field)
        if value is not None and profile.get(field) is None:
            profile[field] = value
    for field in derive.SENSITIVE_ATTRIBUTES:
        value = record.get(field)
        if value is not None and profile.get(field) is None:
            profile[field] = value
    profile["source_record_count"] += 1
    codes = set(profile["contributing_source_system_codes"])
    codes.add(source["code"])
    profile["contributing_source_system_codes"] = sorted(codes)
    stamp = record["event_timestamp"]
    if profile["last_activity_at"] is None or stamp > profile["last_activity_at"]:
        profile["last_activity_at"] = stamp
    tier = _record_tier(record)
    if calc.LOYALTY_ORDINAL[tier] > calc.LOYALTY_ORDINAL[profile["loyalty_tier"]]:
        profile["loyalty_tier"] = tier


def _materialise_consent(profile, record, source):
    groups = set()
    for signal in record.get("consent_signals") or []:
        created = db.new_entity(
            "consent_records",
            profile_id=profile["id"],
            source_system_id=source["id"],
            channel=signal["channel"],
            purpose=signal["purpose"],
            consent_state=signal["consent_state"],
            captured_at=record["event_timestamp"],
            expires_at=None,
            status="ACTIVE",
            precedence_rank=1,
        )
        derive.rerank_consent_group(
            profile["id"], created["channel"], created["purpose"],
            skip_version_ids=(created["id"],),
        )
        groups.add((created["channel"], created["purpose"]))
    return groups


def _linked_ids(profile_id):
    joined = set()
    for link in db.all_of("identity_links"):
        if link["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        if link["left_profile_id"] == profile_id:
            joined.add(link["right_profile_id"])
        elif link["right_profile_id"] == profile_id:
            joined.add(link["left_profile_id"])
    return joined


def _blocking_set(profile):
    joined = _linked_ids(profile["id"])
    blocked = []
    for candidate in candidate_profiles():
        if candidate["id"] == profile["id"] or candidate["id"] in joined:
            continue
        shares = False
        if profile.get("postal_code") is not None \
                and candidate.get("postal_code") == profile["postal_code"]:
            shares = True
        if profile.get("last_name") is not None \
                and candidate.get("last_name") == profile["last_name"]:
            shares = True
        if shares:
            blocked.append(candidate)
    return blocked


def confirm_link(link, rule, actor_id, bump_link=True):
    """Shared confirmation: merge, stamp the link, credit the rule, cascade."""
    left = db.store["profiles"][link["left_profile_id"]]
    right = db.store["profiles"][link["right_profile_id"]]
    survivor, _loser = cascade.merge_profiles(left, right, link)
    link["status"] = "CONFIRMED"
    link["survivor_profile_id"] = survivor["id"]
    link["decided_by_user_id"] = actor_id
    link["decided_at"] = db.now()
    if bump_link:
        db.touch(link)
    else:
        link["updated_at"] = db.now()
    rule["confirmed_count"] += 1
    db.touch(rule)
    cascade.audience_cascade()
    return survivor


def reject_link(link, rule, actor_id):
    link["status"] = "REJECTED"
    link["decided_by_user_id"] = actor_id
    link["decided_at"] = db.now()
    db.touch(link)
    rule["rejected_count"] += 1
    cascade.disable_rule_if_imprecise(rule)
    db.touch(rule)
    return link


def promote_batch(batch, source):
    evaluations = [calc.evaluate_record(record) for record in batch["records"]]
    quality = calc.batch_quality(evaluations, source["dq_scoring_mode"])
    items = [
        (record, evaluation)
        for index, (record, evaluation) in enumerate(zip(batch["records"], evaluations))
        if quality["valid_flags"][index]
    ]
    items.sort(key=lambda pair: (pair[0]["event_timestamp"], pair[0]["external_id"]))

    batch["status"] = "PROMOTED"
    batch["promoted_at"] = db.now()

    deterministic_rules = _enabled_rules("DETERMINISTIC")
    new_count = 0
    deterministic_count = 0
    probabilistic_count = 0
    minted = []
    touched_ids = []
    pre_versions = {}

    # ------------------------------------------- phase one: deterministic
    for record, evaluation in items:
        target = None
        for rule in deterministic_rules:
            field = DETERMINISTIC_FIELD.get(rule["deterministic_key"])
            if field is None:
                continue
            value = evaluation.get(field)
            if value is None:
                continue
            matches = [p for p in candidate_profiles() if p.get(field) == value]
            if len(matches) == 1:
                target = matches[0]
                deterministic_count += 1
                break
        if target is None:
            target = _mint_profile(batch, source, record, evaluation)
            minted.append(target)
            new_count += 1
        else:
            if target["id"] not in pre_versions:
                pre_versions[target["id"]] = target["version"]
            _attach_record(target, source, record, evaluation)
        if target["id"] not in touched_ids:
            touched_ids.append(target["id"])
        _materialise_consent(target, record, source)

    # ----------------------------------------- phase two: probabilistic
    probabilistic_rules = _enabled_rules("PROBABILISTIC")
    for profile in minted:
        for rule in probabilistic_rules:
            if profile["resolution_status"] == "MERGED_AWAY":
                break
            if rule["status"] != "ENABLED":
                continue
            for candidate in _blocking_set(profile):
                if profile["resolution_status"] == "MERGED_AWAY":
                    break
                if candidate["resolution_status"] == "MERGED_AWAY":
                    continue
                evidence = calc.pair_evidence(profile, candidate)
                confidence = calc.match_confidence(evidence, rule["missing_identifier_policy"])
                if confidence < calc.dec(rule["review_floor"]):
                    continue
                link = db.new_entity(
                    "identity_links",
                    left_profile_id=profile["id"],
                    right_profile_id=candidate["id"],
                    match_rule_id=rule["id"],
                    survivor_profile_id=None,
                    evidence=dict(evidence),
                    match_method="PROBABILISTIC",
                    confidence=confidence,
                    status="PROPOSED",
                    decided_by_user_id=None,
                    decided_at=None,
                    void_reason=None,
                )
                probabilistic_count += 1
                if confidence >= calc.dec(rule["auto_merge_threshold"]):
                    confirm_link(link, rule, "system", bump_link=False)

    # -------------------------------------- phase three: resolution settle
    for profile_id in touched_ids:
        profile = db.store["profiles"].get(profile_id)
        if profile is None or profile["resolution_status"] != "UNRESOLVED":
            continue
        outstanding = any(
            link["status"] == "PROPOSED"
            and profile_id in (link["left_profile_id"], link["right_profile_id"])
            for link in db.all_of("identity_links")
        )
        if not outstanding:
            profile["resolution_status"] = "RESOLVED"

    # --------------------------------------- phase four: household grouping
    for profile_id in touched_ids:
        profile = db.store["profiles"].get(profile_id)
        if profile is None or profile["resolution_status"] == "MERGED_AWAY":
            continue
        if profile.get("address_hash") is None or profile["household_id"] is not None:
            continue
        household, created = derive.assign_household(profile)
        if household is not None and not created:
            db.touch(household)

    batch["new_profile_count"] = new_count
    batch["matched_deterministic_count"] = deterministic_count
    batch["matched_probabilistic_count"] = probabilistic_count
    db.touch(batch)

    for profile_id, version in pre_versions.items():
        profile = db.store["profiles"].get(profile_id)
        if profile is None:
            continue
        if profile["version"] == version:
            db.touch(profile)
        else:
            profile["updated_at"] = db.now()

    if source["status"] == "REGISTERED":
        source["status"] = "ACTIVE"
        db.touch(source)
    return batch
