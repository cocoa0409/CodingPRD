"""Corner — endpoints (FK reverse-reachability), RBAC denial, and OCC
stale-version checks.
"""
from test_helpers import (
    amend_result_payload,
    api_client,
    ApiErrorId,
    bootstrap_actors,
    create_instrument_run,
    complete_instrument_run,
    create_lab_order_payload,
    create_order,
    create_result,
    create_result_payload,
    get_lab_order_version,
    get_success_data,
    make_lab_director_headers,
    make_lab_tech_headers,
    make_ordering_provider_headers,
    make_phlebotomist_headers,
    register_director,
    register_lab_tech,
    register_ordering_provider,
    register_patient,
    register_phlebotomist,
    release_result,
    release_result_payload,
    set_clock,
    setup_released_result,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestListLabOrdersFilteredByPatient:
    def test_per_patient_listing_and_global_filter_return_matching_orders(self, api):
        """PRD §4 (endpoint table): "List lab orders for a patient."
        PRD §4 (endpoint table): "List lab orders with optional `patient_id`, `ordering_clinician_id`, `status` filters."

        Design: Corner/endpoints/list_lab_orders_filtered_by_patient_id
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", with_instrument=False)
        pat_a = register_patient(actors.lt_id, mrn="MRN-LRA100")
        pat_b = register_patient(actors.lt_id, mrn="MRN-LRB100")
        ord_a1 = create_order(actors, pat_a["id"], panel_code="CMP")
        ord_a2 = create_order(actors, pat_a["id"], panel_code="CBC")
        ord_b1 = create_order(actors, pat_b["id"], panel_code="GLUC", priority="STAT")

        # Patient A — nested listing.
        res_a = api_client.list_patient_lab_orders(pat_a["id"], actors.lt_headers)
        data_a, meta_a = validate_paginated(res_a)
        ids_a = {row["id"] for row in data_a}
        assert ord_a1["id"] in ids_a, f"ord_a1 must be in patient A listing; got {ids_a}"
        assert ord_a2["id"] in ids_a, f"ord_a2 must be in patient A listing; got {ids_a}"
        assert ord_b1["id"] not in ids_a, f"ord_b1 must NOT leak to patient A; got {ids_a}"

        # Global listing with patient_id filter for B.
        res_b = api_client.list_lab_orders(
            actors.lt_headers, params={"patient_id": pat_b["id"]}
        )
        data_b, meta_b = validate_paginated(res_b)
        ids_b = {row["id"] for row in data_b}
        assert ord_b1["id"] in ids_b, f"ord_b1 must be in patient B filter; got {ids_b}"
        assert ord_a1["id"] not in ids_b, f"ord_a1 must NOT appear; got {ids_b}"
        assert ord_a2["id"] not in ids_b, f"ord_a2 must NOT appear; got {ids_b}"


class TestPhlebotomistCannotCreateLabOrder:
    def test_phlebotomist_post_lab_order_returns_unauthorized(self, api):
        """PRD §2.1: "A request whose `X-User-Role` is syntactically valid but is not
        authorized for the called endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4 endpoint table: POST /patients/{patient_id}/lab-orders is authorized
        only for OrderingProvider.

        Design: Corner/rbac/phlebotomist_cannot_create_lab_order
        """
        director = register_director()
        set_clock("2026-05-28T08:00:00Z", director["id"])
        lt = register_lab_tech(director["id"])
        phleb = register_phlebotomist(director["id"])
        op = register_ordering_provider(director["id"])
        patient = register_patient(lt["id"], mrn="MRN-RB1A00")

        res = api_client.create_lab_order(
            patient["id"],
            create_lab_order_payload(
                ordering_clinician_id=op["id"],
                panel_code="CMP",
                priority="ROUTINE",
            ),
            make_phlebotomist_headers(phleb["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


class TestLabTechCannotInvalidateResult:
    def test_lab_tech_post_invalidate_returns_unauthorized(self, api):
        """PRD §3.8: "Invalidating a result is the lab director's prerogative: only a
        clinician whose `role_type` is `LAB_DIRECTOR` may transition a result from
        `RELEASED` to `INVALIDATED`."

        Design: Corner/rbac/lab_tech_cannot_invalidate_result
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(actors.lt_id, mrn="MRN-RB2A00")
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        # As LabTech, not LabDirector.
        res = api_client.invalidate_result(bundle["result"]["id"], actors.lt_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


class TestOccStaleLabOrderVersionOnRelease:
    def test_release_with_pre_release_lab_order_version_returns_stale_lab_order_version(self, api):
        """PRD §2.6: "A `Result` release MUST include `expected_lab_order_version`, carrying the client's last observed `version` of the parent `LabOrder`."
        PRD §2.6: "the release is rejected with `ERR_STALE_LAB_ORDER_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_lab_order_version_on_release
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(actors.lt_id, mrn="MRN-OC0100")
        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        # Single specimen, walk to ACCESSIONED. Two runs for two distinct Results.
        from test_helpers import (
            accession_specimen,
            collect_specimen,
            create_specimen,
            transit_specimen,
        )
        sp = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])
        accession_specimen(actors, sp["id"])
        run1 = create_instrument_run(
            actors, sp["id"], "2026-05-28T08:30:00Z", "2026-05-28T08:40:00Z"
        )
        complete_instrument_run(actors, run1["id"])
        run2 = create_instrument_run(
            actors, sp["id"], "2026-05-28T08:45:00Z", "2026-05-28T08:55:00Z"
        )
        complete_instrument_run(actors, run2["id"])
        res1 = create_result(
            actors, order["id"], sp["id"], run1["id"],
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        res2 = create_result(
            actors, order["id"], sp["id"], run2["id"],
            analyte_code="GLUCOSE", numeric_value=95.00, unit="mg/dL",
            reference_low=70.00, reference_high=110.00,
            critical_low=40.00, critical_high=500.00,
        )
        # Client captures the pre-release version.
        pre_release_v = get_lab_order_version(actors, order["id"])
        # First release succeeds and bumps order.version.
        release_result(actors, res1["id"], pre_release_v)
        # Second release with the now-stale pre_release_v → ERR_STALE_LAB_ORDER_VERSION.
        res = api_client.release_result(
            res2["id"], release_result_payload(pre_release_v), actors.lt_headers
        )
        validate_error(res, ApiErrorId.ERR_STALE_LAB_ORDER_VERSION)


class TestOccStaleResultVersionOnAmend:
    def test_amend_with_pre_amend_result_version_returns_stale_result_version(self, api):
        """PRD §2.6: "A `Result` amendment MUST include `expected_result_version`,
        carrying the client's last observed `version` of the `Result` being amended.
        If the result's `version` has advanced since the client read it — typically
        because another `LabTech` has already amended the same row and a fresh
        `RELEASED` descendant now exists — the amendment is rejected with
        `ERR_STALE_RESULT_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_result_version_on_amend
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(actors.lt_id, mrn="MRN-SR0100")
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        # Capture pre-amend version of the original Result row.
        pre_amend_v = bundle["result"]["version"]
        # First amend succeeds — bumps Result.version on the original row.
        from test_helpers import amend_result
        amend_result(actors, bundle["result"]["id"], pre_amend_v, 4.50)
        # Second amend on the SAME original row using the stale pre_amend_v →
        # ERR_STALE_RESULT_VERSION per PRD §2.6. PRD §2.10 places state-validity
        # checks ahead of OCC stale-version checks in the priority order, so a
        # faithful implementation may report ERR_INVALID_STATE (the original row
        # is now AMENDED after the first successful amend) instead of the OCC
        # error on this race. PRD names ERR_STALE_RESULT_VERSION as one possible
        # outcome but does not pre-empt the earlier state-check path.
        res = api_client.amend_result(
            bundle["result"]["id"],
            amend_result_payload(pre_amend_v, 4.80),
            actors.lt_headers,
        )
        validate_error_is_one_of(
            res,
            [ApiErrorId.ERR_STALE_RESULT_VERSION, ApiErrorId.ERR_INVALID_STATE],
        )
