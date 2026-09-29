"""Two requests that breach two rules at once, and which breach the ladder reports."""
from test_helpers import ApiErrorId, assert_share_equals, validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE_OFFICER, PROPERTY_MANAGER


def _radiology_exclusive_standoff(api):
    """An unshielded imaging lease and a reading-room lease, both facing a radiology exclusive."""
    building = fx.register_building(api)
    imaging_suite = fx.register_suite(api, building["id"], suite_number="150", floor=1,
                                      rentable_sf=8000, suite_class="IMAGING",
                                      power_amps_available=600, medical_gas_available=False,
                                      shielding_certified=False)
    reading_suite = fx.register_suite(api, building["id"], suite_number="220", floor=2,
                                      rentable_sf=3000, suite_class="STANDARD_EXAM",
                                      power_amps_available=150)
    exclusive_suite = fx.register_suite(api, building["id"], suite_number="230", floor=2,
                                        rentable_sf=5000, suite_class="STANDARD_EXAM",
                                        power_amps_available=200)
    imaging_tenant = fx.register_tenant(api, legal_name="Clearview Imaging LLC",
                                        primary_specialty="RADIOLOGY")
    reading_tenant = fx.register_tenant(api, legal_name="Second Street Radiology LLC",
                                        primary_specialty="RADIOLOGY")
    exclusive_tenant = fx.register_tenant(api, legal_name="Northgate Orthopedics LLC",
                                          primary_specialty="ORTHOPEDICS")

    imaging_lease = fx.draft_lease(api, building["id"], imaging_suite["id"],
                                   imaging_tenant["id"], base_rent_psf_annual=36.50)
    fx.file_attestation(api, imaging_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, imaging_lease["id"], "Imaging suite, corporate tenant")
    fx.certify(api, imaging_lease["id"], "36.50 psf inside [29.20, 41.98]")
    imaging_lease = fx.execute(api, imaging_lease["id"], "Imaging lease executed")

    reading_lease = fx.draft_lease(api, building["id"], reading_suite["id"],
                                   reading_tenant["id"], base_rent_psf_annual=30.00)
    fx.file_attestation(api, reading_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, reading_lease["id"], "Reading room suite")
    fx.certify(api, reading_lease["id"], "30.00 psf inside [24.00, 34.50]")
    reading_lease = fx.execute(api, reading_lease["id"], "No incumbent exclusive exists yet")

    exclusive_lease = fx.draft_lease(api, building["id"], exclusive_suite["id"],
                                     exclusive_tenant["id"], base_rent_psf_annual=30.00,
                                     exclusive_use_specialty="RADIOLOGY")
    fx.file_attestation(api, exclusive_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, exclusive_lease["id"], "Orthopedics with a radiology exclusive")
    fx.certify(api, exclusive_lease["id"], "30.00 psf inside [24.00, 34.50]")
    exclusive_lease = fx.execute(api, exclusive_lease["id"], "Exclusive granted")

    fx.set_clock_date(api, "2026-09-01")
    return {
        "building": building,
        "imaging_suite": imaging_suite,
        "imaging_lease": imaging_lease,
        "reading_lease": reading_lease,
        "exclusive_lease": exclusive_lease,
    }


def test_the_exclusive_use_rule_is_live_on_its_own_at_commencement(api):
    """The control case: a radiology entrant into an ordinary exam suite is refused on the exclusive.

    PRD: "No other lease in the building whose status is `EXECUTED`, `ACTIVE` or `HOLDOVER`
    holds an `exclusive_use_specialty` equal to this lease's tenant's `primary_specialty` —
    otherwise `ERR_EXCLUSIVE_USE_CONFLICT` (409). This guards `POST /leases/{id}/execute` and
    `POST /leases/{id}/commence`."

    Design: Difficulty/priority_pair_validation_conflict/shielding_safety_outranks_exclusive_use_referential_at_commence
    """
    ctx = _radiology_exclusive_standoff(api)

    refused = api.commence_lease(ctx["reading_lease"]["id"],
                                 {"commencement_note": "Exclusive violated only"},
                                 PROPERTY_MANAGER)
    validate_error(refused, ApiErrorId.ERR_EXCLUSIVE_USE_CONFLICT)
    assert fx.read_lease(api, ctx["reading_lease"]["id"])["status"] == "EXECUTED"
    assert fx.read_lease(api, ctx["exclusive_lease"]["id"])["exclusive_use_specialty"] == \
        "RADIOLOGY"


def test_the_radiation_safety_rule_outranks_the_exclusive_use_rule_on_the_same_request(api):
    """Both rules are breached at once and the safety rule is the one reported.

    PRD: "A lease commencing into an `IMAGING` suite requires that suite's
    `shielding_certified` to be true, and a utility review that requires piped medical gas
    requires the suite's `medical_gas_available` to be true."

    PRD: "A single request can breach several rules at once. When it does, the response is
    determined by the **first** breach in the ladder below and no later check is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/shielding_safety_outranks_exclusive_use_referential_at_commence
    """
    ctx = _radiology_exclusive_standoff(api)

    refused = api.commence_lease(ctx["imaging_lease"]["id"],
                                 {"commencement_note": "Radiology into an unshielded suite"},
                                 PROPERTY_MANAGER)
    validate_error(refused, ApiErrorId.ERR_SHIELDING_CERTIFICATION_MISSING)

    assert fx.read_lease(api, ctx["imaging_lease"]["id"])["status"] == "EXECUTED"
    suite = fx.read_suite(api, ctx["imaging_suite"]["id"])
    assert suite["occupancy_status"] == "RESERVED"
    assert suite["shielding_certified"] is False


def _frozen_building_with_an_over_ceiling_lease(api):
    """A lease priced above the published ceiling, in review, inside a frozen building."""
    ctx = fx.drafted_lease(api, lease_overrides={"base_rent_psf_annual": 36.00})
    ctx["lease"] = fx.submit_for_review(api, ctx["lease"]["id"],
                                        "Aggressive ask, needs certification")
    ctx["building"] = validate_success(api.set_mix_freeze(
        ctx["building"]["id"],
        f.mix_freeze_payload(True, "Portfolio-wide referral compliance audit in progress"),
        COMPLIANCE_OFFICER))
    return ctx


def test_the_freeze_outranks_the_rent_ceiling_breach_at_certification(api):
    """The frozen building refuses certification on the freeze, not on the price.

    PRD: "While a building reads `FROZEN`, every leasing-lifecycle write in it is refused with
    `ERR_BUILDING_MIX_FROZEN`, including the creation of further suites, and that refusal takes
    precedence over the merits of the request itself."

    Design: Difficulty/priority_pair_validation_conflict/mix_frozen_state_outranks_rent_above_ceiling_fiscal_at_certify
    """
    ctx = _frozen_building_with_an_over_ceiling_lease(api)
    assert ctx["building"]["mix_freeze_override"] is True
    assert ctx["building"]["tenant_mix_posture"] == "FROZEN"

    refused = api.certify_fmv(ctx["lease"]["id"],
                              {"certification_note": "Attempt during the freeze"},
                              COMPLIANCE_OFFICER)
    validate_error(refused, ApiErrorId.ERR_BUILDING_MIX_FROZEN)

    lease = fx.read_lease(api, ctx["lease"]["id"])
    assert lease["status"] == "PENDING_FMV_REVIEW"
    assert lease["certified_base_rent_annual"] is None


def test_lifting_the_freeze_surfaces_the_rent_ceiling_breach_hiding_underneath(api):
    """The byte-identical request then reports the fiscal rule the freeze was masking.

    PRD: "At certification, `base_rent_psf_annual` does not exceed the band's
    `certified_fmv_ceiling_psf` — otherwise `ERR_RENT_ABOVE_FMV_CEILING` (422), guarding
    `POST /leases/{id}/certify-fmv`."

    PRD: "The boolean is written to `mix_freeze_override`, and the building's posture is then
    recomputed — which means that clearing a freeze restores the computed posture derived from
    the current lease book rather than resetting it to `BALANCED`."

    Design: Difficulty/priority_pair_validation_conflict/mix_frozen_state_outranks_rent_above_ceiling_fiscal_at_certify
    """
    ctx = _frozen_building_with_an_over_ceiling_lease(api)
    validate_error(
        api.certify_fmv(ctx["lease"]["id"], {"certification_note": "Attempt during the freeze"},
                        COMPLIANCE_OFFICER),
        ApiErrorId.ERR_BUILDING_MIX_FROZEN)

    thawed = validate_success(api.set_mix_freeze(
        ctx["building"]["id"], f.mix_freeze_payload(False, "Audit closed"),
        COMPLIANCE_OFFICER))
    assert thawed["mix_freeze_override"] is False
    assert_share_equals(thawed["anchor_share_pct"], 0.0000, "anchor_share_pct")
    assert thawed["tenant_mix_posture"] == "BALANCED"

    refused = api.certify_fmv(ctx["lease"]["id"],
                              {"certification_note": "Attempt during the freeze"},
                              COMPLIANCE_OFFICER)
    validate_error(refused, ApiErrorId.ERR_RENT_ABOVE_FMV_CEILING)

    lease = fx.read_lease(api, ctx["lease"]["id"])
    assert lease["status"] == "PENDING_FMV_REVIEW"
    assert lease["certified_base_rent_annual"] is None
