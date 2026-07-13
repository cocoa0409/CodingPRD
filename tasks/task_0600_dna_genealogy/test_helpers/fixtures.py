"""Composite setup helpers.

Most interesting claims in this PRD need the system in a state that takes 8-15 API calls
to reach — a customer whose kit has been ordered, activated, received, extracted, batched,
started and finalized before they are `DNA_READY` and may generate a report or be matched.
These helpers encapsulate those preambles so tests can focus on assertions.

Every helper builds its preconditions from scratch through PRD-declared endpoints only;
the database is empty at the start of every test.

Identity threading: the `Customer` role is entity-backed, so every ownership-gated call
below uses `make_customer_headers(<the real Customer.id>)`, never a shared constant.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from . import factories as f
from .test_users import (
    make_customer_headers,
    make_lab_technician_headers,
    make_platform_admin_headers,
    make_privacy_officer_headers,
)

ADMIN = make_platform_admin_headers()
LAB = make_lab_technician_headers()
OFFICER = make_privacy_officer_headers()


# ─── Tier 0: primitives ─────────────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START) -> str:
    """Move the server's logical clock. Returns the echoed current_utc."""
    data = get_success_data(api_client.set_clock(f.set_clock_payload(to_iso8601), ADMIN))
    return data["current_utc"]


def create_customer(email=None, display_name="Test Customer") -> dict:
    payload = f.create_customer_payload(display_name=display_name)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_customer(payload, ADMIN))


def create_subscription(customer_id: str, tier: str = "PLUS") -> dict:
    return get_success_data(
        api_client.create_subscription(
            f.create_subscription_payload(customer_id, tier=tier),
            make_customer_headers(customer_id),
        )
    )


def add_credits(customer_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.add_credits(customer_id, f.add_credits_payload(amount_cents=amount_cents), ADMIN)
    )


# Verification reads are performed with an operator role wherever the PRD authorizes one.
# Operator identities are opaque, so a read never trips an ownership check — which keeps the
# *assertion* about the entity's state independent of who is allowed to look at it. Tests that
# mean to exercise ownership do so explicitly on their own trigger call.

def read_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def read_customer_version(customer_id: str) -> int:
    """Re-read the Customer to obtain a fresh `version` for the report OCC guard (PRD §2.7)."""
    return read_customer(customer_id)["version"]


def read_subscription(subscription_id: str, customer_id: str = None) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def read_subscription_version(subscription_id: str, customer_id: str = None) -> int:
    """Re-read the Subscription for the change-tier OCC guard (PRD §2.7)."""
    return read_subscription(subscription_id)["version"]


def read_kit(kit_id: str) -> dict:
    return get_success_data(api_client.get_kit(kit_id, ADMIN))


def read_sample(sample_id: str) -> dict:
    return get_success_data(api_client.get_sample(sample_id, LAB))


def read_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_lab_batch(batch_id, LAB))


def read_consent_grant(grant_id: str, customer_id: str = None) -> dict:
    # GET /dna/consent-grants/{id} is authorized for Customer and PrivacyOfficer.
    return get_success_data(api_client.get_consent_grant(grant_id, OFFICER))


def read_report(report_id: str, customer_id: str = None) -> dict:
    return get_success_data(api_client.get_report(report_id, ADMIN))


def read_match(match_id: str, customer_id: str = None) -> dict:
    return get_success_data(api_client.get_relative_match(match_id, ADMIN))


def read_tree(tree_id: str, customer_id: str = None) -> dict:
    return get_success_data(api_client.get_family_tree(tree_id, ADMIN))


def read_person(person_id: str, customer_id: str = None) -> dict:
    return get_success_data(api_client.get_tree_person(person_id, ADMIN))


def read_data_request(request_id: str, customer_id: str = None) -> dict:
    # GET /dna/data-requests/{id} is authorized for Customer and PrivacyOfficer.
    return get_success_data(api_client.get_data_request(request_id, OFFICER))


# ─── Tier 1: kit / sample state progression ─────────────────────────────────

def create_kit(customer_id: str, chip_version: str = "V5") -> dict:
    return get_success_data(
        api_client.create_kit(
            f.create_kit_payload(customer_id, chip_version=chip_version),
            make_customer_headers(customer_id),
        )
    )


def activate_kit(kit: dict, customer_id: str) -> dict:
    return get_success_data(
        api_client.activate_kit(
            kit["id"], f.activate_kit_payload(kit["barcode"]), make_customer_headers(customer_id)
        )
    )


def receive_kit(kit_id: str) -> dict:
    """Lab receipt — opens the Sample in RECEIVED and moves dna_status to PROCESSING."""
    return get_success_data(api_client.receive_kit(kit_id, LAB))


def extract_sample(sample_id: str, dna_yield_ng: float = None) -> dict:
    yield_ng = TEST_DEFAULTS["GOOD_YIELD_NG"] if dna_yield_ng is None else dna_yield_ng
    return get_success_data(
        api_client.extract_sample(sample_id, f.extract_payload(dna_yield_ng=yield_ng), LAB)
    )


def requeue_sample(sample_id: str) -> dict:
    return get_success_data(api_client.requeue_sample(sample_id, LAB))


def create_received_sample(customer_id: str, chip_version: str = "V5") -> tuple:
    """customer -> kit -> activate -> receive. Returns (kit, sample) with sample in RECEIVED."""
    kit = create_kit(customer_id, chip_version)
    activate_kit(kit, customer_id)
    sample = receive_kit(kit["id"])
    return kit, sample


def create_extracted_sample(customer_id: str, chip_version: str = "V5") -> tuple:
    """customer -> kit -> activate -> receive -> extract(pass). Returns (kit, sample)."""
    kit, sample = create_received_sample(customer_id, chip_version)
    sample = extract_sample(sample["id"])
    return kit, sample


# ─── Tier 2: instrument / batch ─────────────────────────────────────────────

def create_instrument(chip_version: str = "V5", status: str = "ONLINE", name: str = None) -> dict:
    payload = f.create_instrument_payload(chip_version=chip_version, status=status)
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_lab_instrument(payload, ADMIN))


def create_batch(instrument_id: str, sample_ids=None, run_start_at=None, run_end_at=None) -> dict:
    payload = f.create_batch_payload(instrument_id, sample_ids or [])
    if run_start_at is not None:
        payload["run_start_at"] = run_start_at
    if run_end_at is not None:
        payload["run_end_at"] = run_end_at
    return get_success_data(api_client.create_lab_batch(payload, LAB))


def start_batch(batch_id: str) -> dict:
    return get_success_data(api_client.start_lab_batch(batch_id, LAB))


def finalize_batch(batch_id: str, sample_results) -> dict:
    return get_success_data(
        api_client.finalize_lab_batch(batch_id, f.finalize_batch_payload(sample_results), LAB)
    )


def create_running_batch(sample_ids, chip_version: str = "V5") -> tuple:
    """Instrument (ONLINE) + OPEN batch carrying `sample_ids` + start.
    Returns (instrument, batch); every member sample is now GENOTYPING."""
    instrument = create_instrument(chip_version=chip_version)
    batch = create_batch(instrument["id"], sample_ids)
    batch = start_batch(batch["id"])
    return instrument, batch


# ─── Tier 3: full lifecycle to DNA_READY ────────────────────────────────────

DEFAULT_POPULATION_SCORES = [{"population": "EUR", "raw_score": 100}]
DEFAULT_MARKERS = [1, 2]


def setup_dna_ready_group(specs, tier: str = "PLUS") -> list:
    """Drive N customers all the way to `dna_status == DNA_READY`.

    Each spec is a dict accepting: email, display_name, tier, chip_version,
    genotype_markers, population_scores, call_rate.

    Customers are created in list order (so their `created_at` ordering — and, since the
    logical clock does not advance during setup, their email tie-break — follows the list).
    Samples are grouped by chip version onto one ONLINE instrument per chip, because a batch
    may only carry samples whose kit chip matches the instrument's chip.

    Returns one dict per spec: {customer, subscription, kit, sample, headers, instrument, batch}.
    """
    participants = []
    for spec in specs:
        customer = create_customer(
            email=spec.get("email"), display_name=spec.get("display_name", "Test Customer")
        )
        subscription = create_subscription(customer["id"], spec.get("tier", tier))
        kit, sample = create_extracted_sample(customer["id"], spec.get("chip_version", "V5"))
        participants.append(
            {
                "spec": spec,
                "customer": customer,
                "subscription": subscription,
                "kit": kit,
                "sample": sample,
                "headers": make_customer_headers(customer["id"]),
            }
        )

    by_chip = {}
    for p in participants:
        by_chip.setdefault(p["spec"].get("chip_version", "V5"), []).append(p)

    for chip, members in by_chip.items():
        instrument, batch = create_running_batch([m["sample"]["id"] for m in members], chip)
        results = [
            f.sample_result(
                m["sample"]["id"],
                call_rate=m["spec"].get("call_rate", TEST_DEFAULTS["GOOD_CALL_RATE"]),
                population_scores=m["spec"].get("population_scores", DEFAULT_POPULATION_SCORES),
                genotype_markers=m["spec"].get("genotype_markers", DEFAULT_MARKERS),
            )
            for m in members
        ]
        finalize_batch(batch["id"], results)
        for m in members:
            m["instrument"] = instrument
            m["batch"] = read_batch(batch["id"])
            m["sample"] = read_sample(m["sample"]["id"])
            m["kit"] = read_kit(m["kit"]["id"])
            m["customer"] = read_customer(m["customer"]["id"])

    return participants


def setup_dna_ready_customer(**spec) -> dict:
    """Single-customer shortcut for setup_dna_ready_group. Returns the participant dict."""
    return setup_dna_ready_group([spec])[0]


# ─── Tier 4: consent, reports, matching ─────────────────────────────────────

def grant_consent(customer_id: str, scope: str, effective_from=None, effective_until=None) -> dict:
    payload = f.create_consent_payload(customer_id, scope)
    if effective_from is not None:
        payload["effective_from"] = effective_from
    if effective_until is not None:
        payload["effective_until"] = effective_until
    return get_success_data(
        api_client.create_consent_grant(payload, make_customer_headers(customer_id))
    )


def withdraw_consent(grant_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.withdraw_consent_grant(grant_id, make_customer_headers(customer_id))
    )


def publish_report(customer_id: str, report_type: str = "ETHNICITY", variant: str = "PROVISIONAL") -> dict:
    """Read a fresh Customer.version (publishing bumps it) and generate + publish a report."""
    version = read_customer_version(customer_id)
    payload = f.generate_report_payload(version, report_type=report_type, variant=variant)
    return get_success_data(
        api_client.generate_report(customer_id, payload, make_customer_headers(customer_id))
    )


def recompute_matches(customer_id: str) -> list:
    return get_success_data(
        api_client.recompute_matches(customer_id, make_customer_headers(customer_id))
    )


def setup_matched_pair(
    email_a="pair-a@dna.test",
    email_b="pair-b@dna.test",
    markers_a=None,
    markers_b=None,
    chip_a="V5",
    chip_b="V5",
    tier="PLUS",
) -> dict:
    """Two DNA_READY customers, both holding an ACTIVE RELATIVE_MATCHING grant covering the
    clock, with one recompute already run on side A.

    Returns {a, b, grant_a, grant_b, matches} where `a`/`b` are participant dicts and
    `matches` is the array the recompute returned.
    """
    a, b = setup_dna_ready_group(
        [
            {
                "email": email_a,
                "display_name": "PairA",
                "chip_version": chip_a,
                "genotype_markers": markers_a or [1, 2],
                "tier": tier,
            },
            {
                "email": email_b,
                "display_name": "PairB",
                "chip_version": chip_b,
                "genotype_markers": markers_b or [1, 2],
                "tier": tier,
            },
        ]
    )
    grant_a = grant_consent(a["customer"]["id"], "RELATIVE_MATCHING")
    grant_b = grant_consent(b["customer"]["id"], "RELATIVE_MATCHING")
    matches = recompute_matches(a["customer"]["id"])
    return {"a": a, "b": b, "grant_a": grant_a, "grant_b": grant_b, "matches": matches}


def create_tree_with_root(customer_id: str, tree_name: str, surname: str = "Root") -> tuple:
    """One ACTIVE FamilyTree with exactly one ACTIVE root person (no parent links).
    That root person is what the root-person selector hands a DNA_TREE hint to."""
    tree = get_success_data(
        api_client.create_family_tree(
            f.create_family_tree_payload(customer_id, name=tree_name),
            make_customer_headers(customer_id),
        )
    )
    person = get_success_data(
        api_client.create_tree_person(
            f.create_tree_person_payload(tree["id"], given_name="Root", surname=surname),
            make_customer_headers(customer_id),
        )
    )
    return tree, person


def setup_matched_pair_with_trees(
    email_a="casc-a@dna.test", email_b="casc-b@dna.test"
) -> dict:
    """Full four-hop-cascade precondition: two DNA_READY, matching-consented customers, each
    owning one ACTIVE tree with one ACTIVE root person, and one recompute already run — so
    exactly one ACTIVE RelativeMatch exists, both visible_match_counts are 1, and each root
    person carries one PENDING DNA_TREE hint.

    Returns {a, b, grant_a, grant_b, match, tree_a, person_a, tree_b, person_b}.
    """
    a, b = setup_dna_ready_group(
        [
            {"email": email_a, "display_name": "CascA", "genotype_markers": [1, 2]},
            {"email": email_b, "display_name": "CascB", "genotype_markers": [1, 2]},
        ]
    )
    grant_a = grant_consent(a["customer"]["id"], "RELATIVE_MATCHING")
    grant_b = grant_consent(b["customer"]["id"], "RELATIVE_MATCHING")
    tree_a, person_a = create_tree_with_root(a["customer"]["id"], "Tree A", surname="Alpha")
    tree_b, person_b = create_tree_with_root(b["customer"]["id"], "Tree B", surname="Beta")
    matches = recompute_matches(a["customer"]["id"])
    assert len(matches) == 1, f"Setup failed: expected exactly 1 match, got {len(matches)}"
    return {
        "a": a,
        "b": b,
        "grant_a": grant_a,
        "grant_b": grant_b,
        "match": matches[0],
        "tree_a": tree_a,
        "person_a": person_a,
        "tree_b": tree_b,
        "person_b": person_b,
    }


# ─── Tier 5: billing state, privacy terminal states ─────────────────────────

def billing_event(subscription_id: str, event_type: str) -> dict:
    return get_success_data(
        api_client.billing_event(subscription_id, f.billing_event_payload(event_type), ADMIN)
    )


def lock_subscription(subscription_id: str) -> dict:
    """Two PAYMENT_FAILED events: (CURRENT, ACTIVE) -> (PAST_DUE, GRACE) -> (PAST_DUE, LOCKED)."""
    billing_event(subscription_id, "PAYMENT_FAILED")
    return billing_event(subscription_id, "PAYMENT_FAILED")


def setup_upgrade_ready_customer(
    email=None, tier: str = "PLUS", wallet_cents: int = 10_000
) -> dict:
    """Customer + subscription on `tier` with `wallet_cents` of store credit.
    Returns {customer, subscription, headers}."""
    customer = create_customer(email=email, display_name="Upgrader")
    subscription = create_subscription(customer["id"], tier)
    if wallet_cents:
        add_credits(customer["id"], wallet_cents)
    return {
        "customer": read_customer(customer["id"]),
        "subscription": subscription,
        "headers": make_customer_headers(customer["id"]),
    }


def file_data_request(customer_id: str, request_type: str = "EXPORT") -> dict:
    return get_success_data(
        api_client.create_data_request(
            f.create_data_request_payload(customer_id, request_type=request_type),
            make_customer_headers(customer_id),
        )
    )


def decide_data_request(request_id: str, decision: str = "APPROVE", officer_id: str = "po-1") -> dict:
    return get_success_data(
        api_client.decide_data_request(
            request_id, f.decide_payload(decision), make_privacy_officer_headers(officer_id)
        )
    )


def purge_run() -> dict:
    return get_success_data(api_client.purge_run(ADMIN))


def setup_scheduled_delete(customer_id: str) -> dict:
    """File a DELETE request and have it approved, leaving it SCHEDULED with
    scheduled_purge_at set to the decision instant plus seven days."""
    request = file_data_request(customer_id, "DELETE")
    return decide_data_request(request["id"], "APPROVE")


def setup_purged_customer(email=None) -> dict:
    """Customer whose approved DELETE request has been executed by a purge run.
    Advances the clock to the purge instant. Returns {customer, request}."""
    set_clock(CLOCK_START)
    customer = create_customer(email=email, display_name="Purged")
    request = setup_scheduled_delete(customer["id"])
    set_clock("2026-05-08T00:00:00Z")
    purge_run()
    return {"customer": read_customer(customer["id"]), "request": request}


def setup_free_tier_tree_at_limit(email=None) -> dict:
    """FREE-tier customer owning one ACTIVE tree holding exactly 3 ACTIVE people — the
    FREE tier person limit. Returns {customer, subscription, tree, people, headers}."""
    customer = create_customer(email=email, display_name="Limited")
    subscription = create_subscription(customer["id"], "FREE")
    headers = make_customer_headers(customer["id"])
    tree = get_success_data(
        api_client.create_family_tree(
            f.create_family_tree_payload(customer["id"], name="Limited"), headers
        )
    )
    people = []
    for given, surname in (("One", "Aa"), ("Two", "Bb"), ("Three", "Cc")):
        people.append(
            get_success_data(
                api_client.create_tree_person(
                    f.create_tree_person_payload(
                        tree["id"], given_name=given, surname=surname
                    ),
                    headers,
                )
            )
        )
    return {
        "customer": customer,
        "subscription": subscription,
        "tree": read_tree(tree["id"], customer["id"]),
        "people": people,
        "headers": headers,
    }
