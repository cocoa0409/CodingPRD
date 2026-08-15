"""GIS as-built closeout and the application completion checklist."""
from test_helpers import (
    ApiErrorId,
    TWO_ASPHALT_CROSSINGS,
    TWO_LOADS,
    complete_turn_on_payload,
    confirm_booking,
    create_booking,
    create_crew,
    create_gis_as_built_payload,
    create_inspector_payload,
    create_meter_set_payload,
    create_turn_on_event_payload,
    get_success_data,
    make_inspector_headers,
    pay_invoice,
    record_as_built_payload,
    record_purge_leak_test,
    refresh_application,
    refresh_gis,
    refresh_invoice,
    refresh_main_extension,
    setup_ciac_pending_app,
    setup_gis_review_app,
    validate_error,
)


def _advance_to_energized(ctx, api, admin_headers, engineer_headers, technician_headers):
    """From SERVICE_INSTALLED: meter chain, certified PASS test, all loads
    verified, energize. Returns the meter set id."""
    ms = get_success_data(
        api.create_meter_set(create_meter_set_payload(ctx["app"]["id"]),
                             technician_headers)
    )
    get_success_data(api.size_meter_set(ms["id"], engineer_headers))
    get_success_data(
        api.mark_meter_ordered(ms["id"], {"serial_number": "M-9001"}, technician_headers)
    )
    get_success_data(api.install_meter_set(ms["id"], technician_headers))
    plt = record_purge_leak_test(ms["id"], observed_pressure_drop_psi=0.200)
    inspector = get_success_data(
        api.create_inspector(create_inspector_payload(), admin_headers)
    )
    get_success_data(
        api.certify_purge_leak_test(plt["id"], make_inspector_headers(inspector["id"]))
    )
    for load in ctx["loads"]:
        event = get_success_data(
            api.create_turn_on_event(
                create_turn_on_event_payload(ctx["app"]["id"], load["id"]),
                technician_headers,
            )
        )
        get_success_data(
            api.complete_turn_on_event(event["id"], complete_turn_on_payload(),
                                       technician_headers)
        )
    get_success_data(api.energize_application(ctx["app"]["id"], technician_headers))
    return ms["id"]


class TestGisCycle:
    def test_reject_resubmit_validate_cycle(self, api, gis_analyst_headers,
                                            supervisor_headers):
        """PRD §3.8: "Submission starts the record in `SUBMITTED`, stamps `submitted_by_user_id`, and slides the application from `ENERGIZED` into `GIS_REVIEW`. A `GISAnalyst` then validates it — cover depth of at least eighteen inches is code, and anything shallower is rejected with `ERR_GIS_DEPTH_VIOLATION` (HTTP 422) — stamping `validated_by_user_id` as the record moves to the terminal `VALIDATED`; or the analyst rejects it with a `rejection_reason`, sending it to `REJECTED`, from which the supervisor may resubmit corrected `geometry_geojson`, `pipe_material`, or `depth_inches` and return it to `SUBMITTED`."

        Design: Corner/state_machines/gis_reject_resubmit_cycle
        """
        ctx = setup_gis_review_app(depth_inches=16.0)
        assert ctx["gis"]["status"] == "SUBMITTED"
        assert ctx["app"]["status"] == "GIS_REVIEW"

        rejected = get_success_data(
            api.reject_gis(ctx["gis"]["id"], {"rejection_reason": "depth below code"},
                           gis_analyst_headers)
        )
        assert rejected["status"] == "REJECTED"

        resubmitted = get_success_data(
            api.resubmit_gis(ctx["gis"]["id"], {"depth_inches": 24.0}, supervisor_headers)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["depth_inches"] == 24.0

        validated = get_success_data(
            api.validate_gis(ctx["gis"]["id"], gis_analyst_headers)
        )
        assert validated["status"] == "VALIDATED"
        assert validated["validated_by_user_id"] == "gis-1"

    def test_depth_below_code_rejected_at_validate(self, api, gis_analyst_headers):
        """PRD §3.8: "cover depth of at least eighteen inches is code, and anything shallower is rejected with `ERR_GIS_DEPTH_VIOLATION` (HTTP 422)"

        Design: Corner/errors/gis_depth_violation_rejected
        """
        ctx = setup_gis_review_app(depth_inches=16.0)
        assert ctx["gis"]["status"] == "SUBMITTED", (
            "a shallow record is still accepted at data entry; the code check "
            "runs at validation"
        )

        resp = api.validate_gis(ctx["gis"]["id"], gis_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_GIS_DEPTH_VIOLATION, expected_status=422)
        assert refresh_gis(ctx["gis"]["id"])["status"] == "SUBMITTED"

    def test_supervisor_cannot_validate_own_submission(self, api, supervisor_headers):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: validate is listed for GISAnalyst.

        Design: Corner/rbac/supervisor_cannot_validate_gis
        """
        ctx = setup_gis_review_app(depth_inches=24.0)
        assert ctx["gis"]["submitted_by_user_id"] == "sup-1"

        resp = api.validate_gis(ctx["gis"]["id"], supervisor_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
        assert refresh_gis(ctx["gis"]["id"])["status"] == "SUBMITTED"


class TestCompletionGates:
    def test_complete_without_validated_gis_rejected(self, api, admin_headers,
                                                     clerk_headers, engineer_headers,
                                                     rep_headers, supervisor_headers,
                                                     technician_headers):
        """PRD §3.8: "It demands an unheld application, a `VALIDATED` GIS as-built on file (`ERR_GIS_NOT_VALIDATED`, HTTP 422), a `FINALIZED` main extension (`ERR_INVALID_STATE`), and a CIAC invoice in `SETTLED` or `REFUNDED` (`ERR_CIAC_UNPAID`)."

        Design: Corner/validations/complete_without_gis_rejected
        """
        ctx = setup_ciac_pending_app(design_footage_ft=100, crossings=[])
        crew = create_crew(specialty="SERVICE_LINE")
        booking = create_booking(ctx["app"]["id"], crew["id"], scope="SERVICE_INSTALL")
        confirm_booking(booking["id"])
        get_success_data(api.schedule_construction(ctx["app"]["id"], supervisor_headers))
        get_success_data(api.complete_booking(booking["id"], supervisor_headers))
        get_success_data(
            api.record_as_built(ctx["me"]["id"], record_as_built_payload(),
                                supervisor_headers)
        )
        get_success_data(api.finalize_main_extension(ctx["me"]["id"], clerk_headers))
        assert refresh_main_extension(ctx["me"]["id"])["status"] == "FINALIZED"
        assert refresh_invoice(ctx["invoice"]["id"])["status"] == "SETTLED"

        _advance_to_energized(ctx, api, admin_headers, engineer_headers,
                              technician_headers)
        assert refresh_application(ctx["app"]["id"])["status"] == "ENERGIZED"

        resp = api.complete_application(ctx["app"]["id"], rep_headers)
        validate_error(resp, ApiErrorId.ERR_GIS_NOT_VALIDATED, expected_status=422)
        after = refresh_application(ctx["app"]["id"])
        assert after["status"] == "ENERGIZED"
        assert not after.get("completed_at")

    def test_complete_with_reopened_invoice_rejected(self, api, admin_headers,
                                                     clerk_headers, coordinator_headers,
                                                     engineer_headers,
                                                     gis_analyst_headers, rep_headers,
                                                     supervisor_headers,
                                                     technician_headers):
        """PRD §3.8: "It demands an unheld application, a `VALIDATED` GIS as-built on file (`ERR_GIS_NOT_VALIDATED`, HTTP 422), a `FINALIZED` main extension (`ERR_INVALID_STATE`), and a CIAC invoice in `SETTLED` or `REFUNDED` (`ERR_CIAC_UNPAID`)."
        PRD §3.8: "The invoice is then trued-up: an invoice already `PAID` reopens to `ISSUED` with `amount_due_cents` repriced to the final total when the delta is positive"

        Design: Corner/validations/complete_with_unpaid_supplement_rejected
        """
        ctx = setup_ciac_pending_app(
            loads=list(TWO_LOADS), design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS, rock=False,
        )
        pay_invoice(ctx["invoice"]["id"], 322785)

        from test_helpers import create_approved_road_cut_permit
        create_approved_road_cut_permit(ctx["app"]["id"])
        crew = create_crew(specialty="MAIN_EXTENSION")
        booking = create_booking(ctx["app"]["id"], crew["id"], scope="MAIN_CONSTRUCTION")
        confirm_booking(booking["id"])
        get_success_data(api.schedule_construction(ctx["app"]["id"], supervisor_headers))
        get_success_data(api.complete_booking(booking["id"], supervisor_headers))

        _advance_to_energized(ctx, api, admin_headers, engineer_headers,
                              technician_headers)
        gis = get_success_data(
            api.create_gis_as_built(
                create_gis_as_built_payload(ctx["app"]["id"], depth_inches=24.0),
                supervisor_headers,
            )
        )
        get_success_data(api.validate_gis(gis["id"], gis_analyst_headers))
        assert refresh_application(ctx["app"]["id"])["status"] == "GIS_REVIEW"

        # The as-built is larger than the design: the true-up reopens the PAID
        # invoice with a balance of 759493 still owed.
        get_success_data(
            api.record_as_built(
                ctx["me"]["id"],
                record_as_built_payload(
                    actual_footage_ft=220,
                    actual_unit_cost_cents=4750,
                    actual_rock_excavation=True,
                    actual_crossings=[
                        {"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0},
                        {"surface_type": "ASPHALT", "length_ft": 8.0, "width_ft": 3.0},
                        {"surface_type": "CONCRETE", "length_ft": 5.0, "width_ft": 3.0},
                    ],
                ),
                supervisor_headers,
            )
        )
        get_success_data(api.finalize_main_extension(ctx["me"]["id"], clerk_headers))
        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "ISSUED"
        assert invoice["balance_due_cents"] == 759493

        resp = api.complete_application(ctx["app"]["id"], rep_headers)
        validate_error(resp, ApiErrorId.ERR_CIAC_UNPAID, expected_status=422)

        assert refresh_application(ctx["app"]["id"])["status"] == "GIS_REVIEW"
        assert refresh_main_extension(ctx["me"]["id"])["status"] == "FINALIZED"
        assert refresh_gis(gis["id"])["status"] == "VALIDATED", (
            "the referential gate passed; only the fiscal gate failed"
        )
