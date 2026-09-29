"""Setup helpers that build state exclusively through the PRD's own endpoints.

Every helper drives the documented workflow rather than reaching behind the API,
and every helper uses `get_success_data`, so a broken setup step reports itself as
a setup failure rather than as a mysterious assertion deeper in a test.

The server is restarted with an empty store before each test, so each helper
starts from nothing and composes upwards.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .constants import CLOCK_STARTUP_DEFAULT, TEST_DEFAULTS
from .factories import (
    create_archive_payload,
    create_asset_payload,
    create_delivery_package_payload,
    create_eo_application_payload,
    create_eo_review_payload,
    create_fair_use_analysis_payload,
    create_license_payload,
    create_negotiation_round_payload,
    create_opinion_letter_payload,
    create_production_payload,
    create_rate_card_payload,
    create_source_candidate_payload,
    create_subject_release_payload,
    pin_clearance_chart_payload,
    renew_license_payload,
    select_source_payload,
    set_clock_payload,
    state_payload,
)
from .test_users import (
    ARCHIVE_RESEARCHER,
    CLEARANCE_SUPERVISOR,
    LEGAL_COUNSEL,
    PRODUCTION_ADMIN,
    REVIEWING_COUNSEL,
    make_rights_holder_rep_headers,
)

# ─── Logical clock (PRD §2.11) ───────────────────────────────────────────────


def set_clock(api, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the server's logical UTC clock. Reads 2026-08-01T00:00:00Z until called."""
    return get_success_data(
        api.set_clock(set_clock_payload(to_iso8601), headers or PRODUCTION_ADMIN))


def reset_clock_to_startup_default(api) -> Dict[str, Any]:
    return set_clock(api, CLOCK_STARTUP_DEFAULT)


# ─── Productions ─────────────────────────────────────────────────────────────


def create_production(api, **overrides) -> Dict[str, Any]:
    """A production in DEVELOPMENT with posture OPEN and every counter at zero."""
    return get_success_data(
        api.create_production(create_production_payload(**overrides), PRODUCTION_ADMIN), 201)


def drive_production(api, production_id: str, to_status: str,
                     headers: Optional[Dict[str, str]] = None, **body) -> Dict[str, Any]:
    return get_success_data(
        api.set_production_state(production_id, state_payload(to_status, **body),
                                 headers or CLEARANCE_SUPERVISOR))


def create_production_in_clearance(api, **overrides) -> Dict[str, Any]:
    """A production moved DEVELOPMENT → CLEARANCE so assets and licences may attach."""
    production = create_production(api, **overrides)
    return drive_production(api, production["id"], "CLEARANCE", PRODUCTION_ADMIN)


def get_production(api, production_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_production(production_id, headers or CLEARANCE_SUPERVISOR))


def get_production_version(api, production_id: str) -> int:
    """Re-read the production's current `version` — mandatory before pinning a chart."""
    return get_production(api, production_id)["version"]


# ─── Archives and rate cards ─────────────────────────────────────────────────


def create_archive(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_archive(create_archive_payload(**overrides), ARCHIVE_RESEARCHER), 201)


def create_rate_card(api, archive_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_rate_card(archive_id, create_rate_card_payload(**overrides),
                             ARCHIVE_RESEARCHER), 201)


def create_archive_with_rate_card(api, archive_overrides: Optional[Dict] = None,
                                  card_overrides: Optional[Dict] = None
                                  ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An ACTIVE archive holding exactly one ACTIVE card on the standard pricing."""
    archive = create_archive(api, **(archive_overrides or {}))
    card = create_rate_card(api, archive["id"], **(card_overrides or {}))
    return archive, card


def suspend_archive(api, archive_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_archive_state(archive_id, state_payload("SUSPENDED"), CLEARANCE_SUPERVISOR))


def reinstate_archive(api, archive_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_archive_state(archive_id, state_payload("ACTIVE"), CLEARANCE_SUPERVISOR))


# ─── Assets and source candidates ────────────────────────────────────────────


def create_asset(api, production_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_asset(production_id, create_asset_payload(**overrides),
                         ARCHIVE_RESEARCHER), 201)


def create_music_asset(api, production_id: str, **overrides) -> Dict[str, Any]:
    """A MUSIC asset, whose required leg set is MASTER and PUBLISHING together."""
    defaults = {"asset_type": "MUSIC", "title": "Cue 7 - brass sting"}
    defaults.update(overrides)
    return create_asset(api, production_id, **defaults)


def add_source_candidate(api, asset_id: str, archive_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_source_candidate(asset_id,
                                    create_source_candidate_payload(archive_id, **overrides),
                                    ARCHIVE_RESEARCHER), 201)


def select_source(api, asset_id: str, source_candidate_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.select_source(asset_id, select_source_payload(source_candidate_id),
                          headers or ARCHIVE_RESEARCHER))


def create_asset_with_selected_source(api, production_id: str, archive_id: str,
                                      candidate_overrides: Optional[Dict] = None,
                                      **asset_overrides
                                      ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An asset traced to `archive_id` with that AVAILABLE candidate SELECTED.

    A FOOTAGE licence is refused with `ERR_NO_SELECTED_SOURCE` without this step.
    """
    asset = create_asset(api, production_id, **asset_overrides)
    candidate = add_source_candidate(api, asset["id"], archive_id,
                                     **(candidate_overrides or {}))
    select_source(api, asset["id"], candidate["id"])
    return asset, candidate


def get_asset(api, asset_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_asset(asset_id, headers or CLEARANCE_SUPERVISOR))


# ─── Licences ────────────────────────────────────────────────────────────────


def create_license(api, production_id: str, asset_id: str, archive_id: str,
                   headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_license(create_license_payload(production_id, asset_id, archive_id,
                                                  **overrides),
                           headers or CLEARANCE_SUPERVISOR), 201)


def get_license(api, license_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_license(license_id, headers or CLEARANCE_SUPERVISOR))


def get_license_version(api, license_id: str) -> int:
    """Re-read the licence's current `version` — mandatory on every negotiation round."""
    return get_license(api, license_id)["version"]


def post_licensor_round(api, license_id: str, archive_id: str,
                        proposed_fee_cents: int, note: Optional[str] = None) -> Dict[str, Any]:
    """A LICENSOR round: only the licence's own holder may post it (PRD §3.4).

    The acting `RightsHolderRep` must carry the licence's `archive_id` as its
    `X-User-ID`, so the real archive id is threaded through here.
    """
    extra: Dict[str, Any] = {"note": note} if note is not None else {}
    payload = create_negotiation_round_payload(
        proposed_fee_cents, get_license_version(api, license_id), party="LICENSOR", **extra)
    return get_success_data(
        api.create_negotiation_round(license_id, payload,
                                     make_rights_holder_rep_headers(archive_id)), 201)


def post_producer_round(api, license_id: str, proposed_fee_cents: int,
                        note: Optional[str] = None) -> Dict[str, Any]:
    """A PRODUCER round, postable only by a ProductionAdmin or ClearanceSupervisor."""
    extra: Dict[str, Any] = {"note": note} if note is not None else {}
    payload = create_negotiation_round_payload(
        proposed_fee_cents, get_license_version(api, license_id), party="PRODUCER", **extra)
    return get_success_data(
        api.create_negotiation_round(license_id, payload, CLEARANCE_SUPERVISOR), 201)


def quote_license(api, license_id: str, archive_id: str,
                  proposed_fee_cents: Optional[int] = None) -> Dict[str, Any]:
    """Drive a licence DRAFT → QUOTED with one LICENSOR round, the only route in."""
    if proposed_fee_cents is None:
        proposed_fee_cents = get_license(api, license_id)["rate_card_fee_cents"]
    post_licensor_round(api, license_id, archive_id, proposed_fee_cents)
    return get_license(api, license_id)


def drive_license(api, license_id: str, to_status: str,
                  headers: Optional[Dict[str, str]] = None, **body) -> Dict[str, Any]:
    return get_success_data(
        api.set_license_state(license_id, state_payload(to_status, **body),
                              headers or CLEARANCE_SUPERVISOR))


def execute_license(api, license_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """QUOTED → EXECUTED, which is where the most-favored-nations settlement runs."""
    return drive_license(api, license_id, "EXECUTED", headers)


def terminate_license(api, license_id: str, reason: str = "Chain of title dispute"
                      ) -> Dict[str, Any]:
    return drive_license(api, license_id, "TERMINATED", reason=reason)


def lapse_license(api, license_id: str) -> Dict[str, Any]:
    return drive_license(api, license_id, "LAPSED")


def create_and_execute_license(api, production_id: str, asset_id: str, archive_id: str,
                               proposed_fee_cents: Optional[int] = None,
                               **overrides) -> Dict[str, Any]:
    """Open a licence, quote it, and execute it — the full DRAFT → EXECUTED path."""
    license_row = create_license(api, production_id, asset_id, archive_id, **overrides)
    quote_license(api, license_row["id"], archive_id, proposed_fee_cents)
    return execute_license(api, license_row["id"])


def renew_license(api, license_id: str, additional_term_months: int) -> Dict[str, Any]:
    return get_success_data(
        api.renew_license(license_id, renew_license_payload(additional_term_months),
                          CLEARANCE_SUPERVISOR))


# ─── Fair-use analyses and opinion letters ───────────────────────────────────


def create_fair_use_analysis(api, asset_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_fair_use_analysis(asset_id, create_fair_use_analysis_payload(**overrides),
                                     LEGAL_COUNSEL), 201)


def drive_fair_use_analysis(api, analysis_id: str, to_status: str,
                           headers: Optional[Dict[str, str]] = None, **body) -> Dict[str, Any]:
    return get_success_data(
        api.set_fair_use_analysis_state(analysis_id, state_payload(to_status, **body),
                                        headers or LEGAL_COUNSEL))


def create_opinion_letter(api, analysis_id: str,
                          headers: Optional[Dict[str, str]] = None,
                          **overrides) -> Dict[str, Any]:
    """The acting operator's X-User-ID is captured as `issued_by_user_id` here."""
    return get_success_data(
        api.create_opinion_letter(analysis_id, create_opinion_letter_payload(**overrides),
                                  headers or LEGAL_COUNSEL), 201)


def drive_opinion_letter(api, letter_id: str, to_status: str,
                        headers: Optional[Dict[str, str]] = None, **body) -> Dict[str, Any]:
    return get_success_data(
        api.set_opinion_letter_state(letter_id, state_payload(to_status, **body),
                                     headers or LEGAL_COUNSEL))


def issue_opinion_letter(api, analysis_id: str, issuer_headers: Optional[Dict] = None,
                         **overrides) -> Dict[str, Any]:
    """Attach a letter to a SUBMITTED analysis and move it DRAFT → ISSUED."""
    letter = create_opinion_letter(api, analysis_id, issuer_headers, **overrides)
    return drive_opinion_letter(api, letter["id"], "ISSUED", issuer_headers)


def clear_asset_via_fair_use(api, asset_id: str, issuer_headers: Optional[Dict] = None,
                             letter_overrides: Optional[Dict] = None,
                             **score_overrides) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Take an asset to CLEARED on a FAIR_USE basis.

    The analysis is submitted, a supporting letter is issued, and only then is the
    analysis accepted — the opinion-letter requirement is checked before the score.
    """
    analysis = create_fair_use_analysis(api, asset_id, **score_overrides)
    drive_fair_use_analysis(api, analysis["id"], "SUBMITTED")
    letter = issue_opinion_letter(api, analysis["id"], issuer_headers,
                                 **(letter_overrides or {}))
    analysis = drive_fair_use_analysis(api, analysis["id"], "ACCEPTED",
                                      decision_rationale="Transformative commentary")
    return analysis, letter


# ─── Subject releases ────────────────────────────────────────────────────────


def create_subject_release(api, production_id: str, subject_person_key: str,
                          headers: Optional[Dict[str, str]] = None,
                          **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_subject_release(production_id,
                                  create_subject_release_payload(subject_person_key, **overrides),
                                  headers or PRODUCTION_ADMIN), 201)


def drive_subject_release(api, release_id: str, to_status: str,
                         headers: Optional[Dict[str, str]] = None, **body) -> Dict[str, Any]:
    return get_success_data(
        api.set_subject_release_state(release_id, state_payload(to_status, **body),
                                     headers or PRODUCTION_ADMIN))


def create_live_subject_release(api, production_id: str, subject_person_key: str,
                                to_status: str = "SENT", **overrides) -> Dict[str, Any]:
    """A release taken out of DRAFT so that it blocks a conflicting depiction window."""
    release = create_subject_release(api, production_id, subject_person_key, **overrides)
    drive_subject_release(api, release["id"], "SENT")
    if to_status != "SENT":
        return drive_subject_release(api, release["id"], to_status)
    return get_success_data(api.get_subject_release(release["id"], PRODUCTION_ADMIN))


# ─── Clearance charts ────────────────────────────────────────────────────────


def pin_chart(api, production_id: str, chart_label: str = "v1",
              headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    """Pin a chart, re-reading the production's `version` first as §2.7 requires."""
    payload = pin_clearance_chart_payload(get_production_version(api, production_id),
                                         chart_label, **overrides)
    return get_success_data(
        api.pin_clearance_chart(production_id, payload, headers or CLEARANCE_SUPERVISOR), 201)


def get_chart(api, chart_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_clearance_chart(chart_id, headers or CLEARANCE_SUPERVISOR))


# ─── E&O applications ────────────────────────────────────────────────────────


def open_eo_application(api, production_id: str, clearance_chart_id: str,
                        headers: Optional[Dict[str, str]] = None,
                        **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_eo_application(production_id,
                                 create_eo_application_payload(clearance_chart_id, **overrides),
                                 headers or PRODUCTION_ADMIN), 201)


def drive_eo_application(api, eo_application_id: str, to_status: str,
                        headers: Optional[Dict[str, str]] = None, **body) -> Dict[str, Any]:
    return get_success_data(
        api.set_eo_application_state(eo_application_id, state_payload(to_status, **body),
                                     headers or CLEARANCE_SUPERVISOR))


def submit_eo_application(api, eo_application_id: str) -> Dict[str, Any]:
    """DRAFT → SUBMITTED, which is where the premium is rated and stamped."""
    return drive_eo_application(api, eo_application_id, "SUBMITTED")


def record_eo_review(api, eo_application_id: str, review_type: str, outcome: str = "PASS",
                    headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    """Recording a review branch updates the application rather than creating a
    resource of its own, so PRD §4 makes this a 200 OK operation."""
    if headers is None:
        headers = REVIEWING_COUNSEL if review_type == "LEGAL" else CLEARANCE_SUPERVISOR
    return get_success_data(
        api.create_eo_review(eo_application_id,
                            create_eo_review_payload(review_type, outcome, **overrides),
                            headers), 200)


def record_both_eo_reviews(api, eo_application_id: str, legal_outcome: str = "PASS",
                           underwriting_outcome: str = "PASS",
                           legal_headers: Optional[Dict] = None,
                           underwriting_headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Record both branches with two distinct operators.

    Segregation of duties forbids one operator recording both branches, and forbids
    the legal reviewer being a lawyer whose letter the chart relies upon — hence the
    reviewing counsel identity, distinct from the letter-issuing counsel.
    """
    record_eo_review(api, eo_application_id, "LEGAL", legal_outcome, legal_headers)
    record_eo_review(api, eo_application_id, "UNDERWRITING", underwriting_outcome,
                     underwriting_headers)
    return get_success_data(api.get_eo_application(eo_application_id, CLEARANCE_SUPERVISOR))


def bind_eo_application(api, eo_application_id: str,
                        policy_number: str = "EO-2026-55") -> Dict[str, Any]:
    return drive_eo_application(api, eo_application_id, "BOUND", PRODUCTION_ADMIN,
                                policy_number=policy_number)


def rebind_eo_application(api, eo_application_id: str) -> Dict[str, Any]:
    """REMEDIATION_REQUIRED → BOUND, the cycle back into cover after a cure."""
    return drive_eo_application(api, eo_application_id, "BOUND", PRODUCTION_ADMIN)


def place_bound_eo_cover(api, production_id: str, clearance_chart_id: str,
                        policy_number: str = "EO-2026-55",
                        **application_overrides) -> Dict[str, Any]:
    """Open, submit, review both branches and bind — the full path to BOUND cover."""
    application = open_eo_application(api, production_id, clearance_chart_id,
                                      **application_overrides)
    submit_eo_application(api, application["id"])
    record_both_eo_reviews(api, application["id"])
    return bind_eo_application(api, application["id"], policy_number)


# ─── Delivery packages ───────────────────────────────────────────────────────


def open_delivery_package(api, production_id: str, clearance_chart_id: str,
                          headers: Optional[Dict[str, str]] = None,
                          **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_delivery_package(production_id,
                                   create_delivery_package_payload(clearance_chart_id,
                                                                   **overrides),
                                   headers or PRODUCTION_ADMIN), 201)


def drive_delivery_package(api, package_id: str, to_status: str,
                          headers: Optional[Dict[str, str]] = None, **body) -> Dict[str, Any]:
    return get_success_data(
        api.set_delivery_package_state(package_id, state_payload(to_status, **body),
                                       headers or CLEARANCE_SUPERVISOR))


def validate_delivery_package(api, package_id: str) -> Dict[str, Any]:
    return drive_delivery_package(api, package_id, "VALIDATED")


def deliver_delivery_package(api, package_id: str) -> Dict[str, Any]:
    return drive_delivery_package(api, package_id, "DELIVERED")


def get_delivery_package(api, package_id: str,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_delivery_package(package_id,
                                                     headers or CLEARANCE_SUPERVISOR))


# ─── Rights sweep ────────────────────────────────────────────────────────────


def run_sweep(api, production_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.run_rights_sweep(production_id, headers or CLEARANCE_SUPERVISOR))


# ─── Composite scenarios ─────────────────────────────────────────────────────


def setup_licensed_footage_production(api, asset_overrides: Optional[Dict] = None,
                                      license_overrides: Optional[Dict] = None,
                                      card_overrides: Optional[Dict] = None
                                      ) -> Dict[str, Any]:
    """A production in CLEARANCE whose single footage asset is CLEARED on a licence.

    Returns the ids and rows the scenario tests need: `production`, `archive`,
    `rate_card`, `asset`, `source_candidate` and `license`.
    """
    production = create_production_in_clearance(api)
    archive, card = create_archive_with_rate_card(api, card_overrides=card_overrides)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], **(asset_overrides or {}))
    license_row = create_and_execute_license(
        api, production["id"], asset["id"], archive["id"], **(license_overrides or {}))
    return {
        "production": get_production(api, production["id"]),
        "archive": archive,
        "rate_card": card,
        "asset": get_asset(api, asset["id"]),
        "source_candidate": candidate,
        "license": license_row,
    }


def setup_pinned_chart_production(api, **kwargs) -> Dict[str, Any]:
    """The licensed-footage scenario with a PINNED chart over its single row."""
    scenario = setup_licensed_footage_production(api, **kwargs)
    scenario["chart"] = pin_chart(api, scenario["production"]["id"])
    scenario["production"] = get_production(api, scenario["production"]["id"])
    return scenario


def setup_bound_eo_production(api, policy_number: str = "EO-2026-55",
                              application_overrides: Optional[Dict] = None,
                              **kwargs) -> Dict[str, Any]:
    """A production carrying a PINNED chart and an E&O application in BOUND."""
    scenario = setup_pinned_chart_production(api, **kwargs)
    scenario["eo_application"] = place_bound_eo_cover(
        api, scenario["production"]["id"], scenario["chart"]["id"], policy_number,
        **(application_overrides or {}))
    return scenario


def setup_validated_delivery_package(api, package_overrides: Optional[Dict] = None,
                                     **kwargs) -> Dict[str, Any]:
    """A VALIDATED package over a bound-cover production, one step short of delivery."""
    scenario = setup_bound_eo_production(api, **kwargs)
    package = open_delivery_package(api, scenario["production"]["id"],
                                    scenario["chart"]["id"], **(package_overrides or {}))
    scenario["delivery_package"] = validate_delivery_package(api, package["id"])
    return scenario


def setup_delivered_production(api, **kwargs) -> Dict[str, Any]:
    """A production whose package has reached DELIVERED — the state the sweep and the
    withdrawal cascade both push back into SUSPENDED."""
    scenario = setup_validated_delivery_package(api, **kwargs)
    scenario["delivery_package"] = deliver_delivery_package(
        api, scenario["delivery_package"]["id"])
    scenario["production"] = get_production(api, scenario["production"]["id"])
    return scenario


def setup_music_asset_with_master_leg_only(api, production_id: str, archive_id: str,
                                          **license_overrides) -> Dict[str, Any]:
    """A MUSIC asset holding only its MASTER leg, so PARTIALLY_CLEARED rather than CLEARED.

    A chart pinned over it carries a non-zero `music_leg_gap_count`.
    """
    asset = create_music_asset(api, production_id)
    candidate = add_source_candidate(api, asset["id"], archive_id)
    select_source(api, asset["id"], candidate["id"])
    overrides: Dict[str, Any] = {"rights_leg": "MASTER"}
    overrides.update(license_overrides)
    master = create_and_execute_license(api, production_id, asset["id"], archive_id,
                                        **overrides)
    return {
        "asset": get_asset(api, asset["id"]),
        "source_candidate": candidate,
        "master_license": master,
    }


def setup_fair_use_cleared_production(api, issuer_headers: Optional[Dict] = None,
                                      **score_overrides) -> Dict[str, Any]:
    """A production whose single asset is CLEARED on a FAIR_USE basis.

    The asset is deliberately given no licence at all, so acceptance of the analysis
    is the only thing holding its clearance — which is what the withdrawal cascade
    then removes.
    """
    production = create_production_in_clearance(api)
    asset = create_asset(api, production["id"])
    analysis, letter = clear_asset_via_fair_use(api, asset["id"], issuer_headers,
                                                **score_overrides)
    return {
        "production": get_production(api, production["id"]),
        "asset": get_asset(api, asset["id"]),
        "analysis": analysis,
        "opinion_letter": letter,
    }


def list_all(api_call, headers: Dict[str, str], params: Optional[Dict] = None
             ) -> List[Dict[str, Any]]:
    """Read one page of up to the maximum page size from a collection endpoint."""
    merged = {"limit": 100}
    merged.update(params or {})
    return get_success_data(api_call(headers, params=merged))


def standard_all_media_fee_cents() -> int:
    """The rate-card fee of a 45-second BROADCAST/WORLD/36-month all-media licence."""
    return TEST_DEFAULTS["all_media_window_fee_cents"]
