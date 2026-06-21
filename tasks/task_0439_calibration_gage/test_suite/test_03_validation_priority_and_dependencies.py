"""Validation-priority conflicts, cross-entity state dependencies, and
segregation of duties.

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency.
Corner queue: rbac (segregation of duties).
"""
from test_helpers import validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    TECH, QE, MET,
    create_standard,
    create_vendor,
    create_instrument,
    open_event,
    add_point,
    finalize_failing_event,
    get_only_impact,
    current_version,
    setup_quarantined_instrument,
)
from test_helpers.test_users import (
    make_quality_engineer_headers,
    make_technician_headers,
)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / state_before_segregation_on_disposition
# ===========================================================================
def test_disposition_on_open_impact_by_event_author_returns_invalid_state(api):
    """PRD §2.10: "Only then are state-machine and business-safety rules evaluated:
    that the resource is in a state from which the transition is defined
    (`ERR_INVALID_STATE`)".
    PRD §3.5: "this is permitted only from `INVESTIGATING` (otherwise
    `ERR_INVALID_STATE`) and again enforces that the acting `X-User-ID` differs from
    the triggering event's `performed_by_user_id` (otherwise
    `ERR_SEGREGATION_OF_DUTIES`)."

    The impact is OPEN (not INVESTIGATING) AND the actor equals the event author;
    state precedes segregation, so ERR_INVALID_STATE wins.

    Design: Difficulty/priority_pair_validation_conflict/state_before_segregation_on_disposition
    """
    qe1 = make_quality_engineer_headers("qe-1")
    actor = make_quality_engineer_headers("user-x")
    tech = make_technician_headers("user-x")
    std = create_standard(name="GB-PP1", nist_test_number="NIST-7")
    inst = create_instrument(asset_tag="INST-PP1", criticality="CRITICAL", headers=qe1)
    finalize_failing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.40, tech_headers=tech)
    impact = get_only_impact(inst["id"], headers=qe1)
    validate_error(api.disposition_impact(impact["id"], {"disposition": "USE_AS_IS"}, actor),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_disposition_on_open_impact_by_distinct_engineer_still_invalid_state(api):
    """PRD §3.5: "From `INVESTIGATING` the engineer dispositions the impact ... this
    is permitted only from `INVESTIGATING` (otherwise `ERR_INVALID_STATE`)".

    Isolating the state check from segregation: a DISTINCT (non-author)
    QualityEngineer dispositioning an OPEN (not INVESTIGATING) impact still gets
    ERR_INVALID_STATE — the state precondition fires on its own.

    Design: Difficulty/priority_pair_validation_conflict/state_before_segregation_on_disposition
    """
    qe1 = make_quality_engineer_headers("qe-1")
    distinct = make_quality_engineer_headers("qe-other")
    tech = make_technician_headers("tech-x")
    std = create_standard(name="GB-PP1b", nist_test_number="NIST-7b")
    inst = create_instrument(asset_tag="INST-PP1b", criticality="CRITICAL", headers=qe1)
    finalize_failing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.40, tech_headers=tech)
    impact = get_only_impact(inst["id"], headers=qe1)
    validate_error(api.disposition_impact(impact["id"], {"disposition": "USE_AS_IS"}, distinct),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / instrument_active_before_traceable_on_start
# ===========================================================================
def test_start_on_quarantined_with_untraceable_standard_returns_not_active(api):
    """PRD §2.10: "that the owning instrument is `ACTIVE` where required
    (`ERR_INSTRUMENT_NOT_ACTIVE`)".
    PRD §3.3: "the `standard_id` must resolve to a standard whose `is_traceable` is
    true at the moment of the start (otherwise `ERR_STANDARD_NOT_TRACEABLE`)".

    The instrument is QUARANTINED AND the standard is non-traceable; the
    active-state check (lower priority number) fires first → ERR_INSTRUMENT_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/instrument_active_before_traceable_on_start
    """
    std_good = create_standard(name="GB-Good", nist_test_number="NIST-8",
                               certified_through_epoch=9999)
    std_exp = create_standard(name="GB-Expired", nist_test_number="NIST-9",
                              certified_through_epoch=1)
    inst = create_instrument(asset_tag="INST-PP2", criticality="MAJOR")
    # Quarantine the instrument via a FAIL finalize using the good standard.
    bad = open_event(inst["id"], std_good["id"], inst["version"], scheduled_epoch=5)
    add_point(bad["id"], as_found_value=25.40, as_left_value=25.40)
    validate_success(api.start_event(bad["id"], TECH))
    validate_success(api.finalize_event(bad["id"], TECH))
    # New event referencing the expired (untraceable) standard on the QUARANTINED instrument.
    ev2 = open_event(inst["id"], std_exp["id"], current_version(inst["id"]), scheduled_epoch=6)
    add_point(ev2["id"], as_found_value=25.00)
    validate_error(api.start_event(ev2["id"], TECH),
                   ApiErrorId.ERR_INSTRUMENT_NOT_ACTIVE.value)


def test_start_on_active_with_untraceable_standard_returns_not_traceable(api):
    """PRD §3.3: "the `standard_id` must resolve to a standard whose `is_traceable`
    is true at the moment of the start (otherwise `ERR_STANDARD_NOT_TRACEABLE`)".

    Isolating the traceability check: on an ACTIVE instrument (active check passes)
    the same expired standard makes start fail with ERR_STANDARD_NOT_TRACEABLE,
    proving both checks exist and that the active check wins only when both apply.

    Design: Difficulty/priority_pair_validation_conflict/instrument_active_before_traceable_on_start
    """
    std_exp = create_standard(name="GB-Expired2", nist_test_number="NIST-9b",
                              certified_through_epoch=1)
    inst = create_instrument(asset_tag="INST-PP2b", criticality="MAJOR")
    validate_success(api.advance_clock({"by_epochs": 5}, QE))
    ev = open_event(inst["id"], std_exp["id"], current_version(inst["id"]), scheduled_epoch=6)
    add_point(ev["id"], as_found_value=25.00)
    validate_error(api.start_event(ev["id"], TECH),
                   ApiErrorId.ERR_STANDARD_NOT_TRACEABLE.value)


# ===========================================================================
# Difficulty / cross_entity_state_dependency / event_start_depends_on_instrument_active
# ===========================================================================
def test_event_start_rejected_when_instrument_quarantined(api):
    """PRD §3.3: "The owning instrument must be `ACTIVE` (otherwise
    `ERR_INSTRUMENT_NOT_ACTIVE`)".

    With a fully traceable standard, the only failing precondition is the
    cross-entity instrument lifecycle state (QUARANTINED).

    Design: Difficulty/cross_entity_state_dependency/event_start_depends_on_instrument_active
    """
    std = create_standard(name="GB-CE1", nist_test_number="NIST-11")
    inst = create_instrument(asset_tag="INST-CE1", criticality="MAJOR")
    bad = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    add_point(bad["id"], as_found_value=25.40, as_left_value=25.40)
    validate_success(api.start_event(bad["id"], TECH))
    validate_success(api.finalize_event(bad["id"], TECH))
    ev2 = open_event(inst["id"], std["id"], current_version(inst["id"]), scheduled_epoch=6)
    add_point(ev2["id"], as_found_value=25.00)
    validate_error(api.start_event(ev2["id"], TECH),
                   ApiErrorId.ERR_INSTRUMENT_NOT_ACTIVE.value)


def test_event_start_succeeds_when_instrument_active(api):
    """PRD §3.3: "Starting an event advances it from `DRAFT` to `IN_PROGRESS` ... The
    owning instrument must be `ACTIVE` (otherwise `ERR_INSTRUMENT_NOT_ACTIVE`)".
    PRD §3.3: "A successful start sets `status` to `IN_PROGRESS` and increments the
    event's version."

    The positive complement: with the instrument ACTIVE and a traceable standard,
    the cross-entity dependency is satisfied and start succeeds — confirming the
    instrument lifecycle state is the discriminator.

    Design: Difficulty/cross_entity_state_dependency/event_start_depends_on_instrument_active
    """
    std = create_standard(name="GB-CE1b", nist_test_number="NIST-11b")
    inst = create_instrument(asset_tag="INST-CE1b", criticality="MAJOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    add_point(ev["id"], as_found_value=25.00)
    data = validate_success(api.start_event(ev["id"], TECH))
    assert data["status"] == "IN_PROGRESS", \
        f"expected IN_PROGRESS on an ACTIVE instrument, got {data['status']}"


# ===========================================================================
# Difficulty / cross_entity_state_dependency / cert_verify_depends_on_event_finalized
# ===========================================================================
def test_certificate_verify_rejected_when_event_not_finalized(api):
    """PRD §3.6: "From `ISSUED` a `Metrologist` verifies it to `VERIFIED`
    (terminal), which requires that the owning calibration event be in `PASSED` or
    `CONDITIONAL_PASS` (otherwise `ERR_EVENT_NOT_FINALIZED`)".

    The owning event is still IN_PROGRESS → ERR_EVENT_NOT_FINALIZED.

    Design: Difficulty/cross_entity_state_dependency/cert_verify_depends_on_event_finalized
    """
    std = create_standard(name="GB-CE2", nist_test_number="NIST-12")
    vendor = create_vendor(name="AccLab", accreditation_body="A2LA",
                           accreditation_number="A2LA-001")
    inst = create_instrument(asset_tag="INST-CE2", criticality="MAJOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5,
                    vendor_id=vendor["id"])
    add_point(ev["id"], as_found_value=25.00)
    validate_success(api.start_event(ev["id"], TECH))
    cert = validate_success(api.issue_certificate(
        ev["id"], {"vendor_id": vendor["id"], "certificate_number": "CERT-1",
                   "issued_epoch": 5}, MET), 201)
    validate_error(api.verify_certificate(cert["id"], MET),
                   ApiErrorId.ERR_EVENT_NOT_FINALIZED.value)


def test_certificate_verify_succeeds_once_event_finalized(api):
    """PRD §3.6: "From `ISSUED` a `Metrologist` verifies it to `VERIFIED`
    (terminal), which requires that the owning calibration event be in `PASSED` or
    `CONDITIONAL_PASS` (otherwise `ERR_EVENT_NOT_FINALIZED`), that the certificate's
    `vendor_id` equal the owning event's `vendor_id` (otherwise
    `ERR_CERT_VENDOR_MISMATCH`), and that the issuing vendor's
    `is_accreditation_current` be true (otherwise `ERR_VENDOR_NOT_ELIGIBLE`)."

    The positive complement: once the owning event is finalized to PASSED (and the
    vendor matches and is accredited), verify succeeds to VERIFIED — pinning the
    cross-entity dependency on the event's finalized state.

    Design: Difficulty/cross_entity_state_dependency/cert_verify_depends_on_event_finalized
    """
    std = create_standard(name="GB-CE2b", nist_test_number="NIST-12b")
    vendor = create_vendor(name="AccLab2", accreditation_body="A2LA",
                           accreditation_number="A2LA-002")
    inst = create_instrument(asset_tag="INST-CE2b", criticality="MAJOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5,
                    vendor_id=vendor["id"])
    add_point(ev["id"], as_found_value=25.00)
    validate_success(api.start_event(ev["id"], TECH))
    cert = validate_success(api.issue_certificate(
        ev["id"], {"vendor_id": vendor["id"], "certificate_number": "CERT-2",
                   "issued_epoch": 5}, MET), 201)
    validate_success(api.finalize_event(ev["id"], TECH))
    data = validate_success(api.verify_certificate(cert["id"], MET))
    assert data["status"] == "VERIFIED", \
        f"expected VERIFIED once the event is finalized, got {data['status']}"


# ===========================================================================
# Corner / rbac / corner_segregation_of_duties_denial
# ===========================================================================
def test_segregation_of_duties_blocks_event_author_investigating(api):
    """PRD §3.5: "but only from `OPEN` (otherwise `ERR_INVALID_STATE`) and only when
    the acting `X-User-ID` differs from the triggering event's `performed_by_user_id`
    — the technician who ran the failed calibration may not investigate its fallout
    (otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."

    The investigating engineer's X-User-ID equals the event author's id.

    Design: Corner/rbac/corner_segregation_of_duties_denial
    """
    qe0 = make_quality_engineer_headers("qe-0")
    tech_shared = make_technician_headers("shared-1")
    qe_shared = make_quality_engineer_headers("shared-1")
    std = create_standard(name="S-SOD", nist_test_number="NIST-SOD")
    inst = create_instrument(asset_tag="INST-SOD", criticality="CRITICAL", headers=qe0)
    finalize_failing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.40, tech_headers=tech_shared)
    impact = get_only_impact(inst["id"], headers=qe0)
    validate_error(api.investigate_impact(impact["id"], qe_shared),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
