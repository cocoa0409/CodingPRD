"""Regulatory documentation: STC conformity path, FAA field approval, and loops."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_regulatory_package,
    create_regulatory_package,
    get_regulatory_package,
    make_inspector_headers,
    record_package_decision,
    setup_approved_work_order,
    setup_pending_approval,
    submit_package,
    validate_error,
    validate_paginated,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestFieldApprovalCycle:
    def test_faa_rejection_loops_back_to_draft(self, api):
        """PRD §3.6: "Submitting an `STC` package moves it from `DRAFT` to `CONFORMITY_REVIEW`; submitting a `FIELD_APPROVAL` package moves it from `DRAFT` to `FAA_SUBMITTED` and mints an `faa_tracking_number` on that first submission, a number retained unchanged across any later resubmissions."
        PRD §3.6: "A `decision` of `REJECTED` sends the package back to `DRAFT` — the conformity-rejection loop for STC data, the FAA-rejection loop for field approvals — where the data is corrected in place and resubmitted through the same path-dependent submission."

        Design: Difficulty/non_linear_state_machine/regulatory_faa_rejection_cycle
        """
        bundle = setup_approved_work_order(customer_name="FAA Owner",
                                           customer_email="faa@x.com",
                                           equipment_list=[])
        package = create_regulatory_package(bundle["work_order"]["id"],
                                            approval_path="FIELD_APPROVAL")
        submitted = submit_package(package["id"])
        assert submitted["status"] == "FAA_SUBMITTED"
        tracking = submitted["faa_tracking_number"]
        assert isinstance(tracking, str) and tracking, (
            "first field-approval submission mints the tracking number")

        rejected = record_package_decision(package["id"], "REJECTED",
                                           inspector_id="insp-1")
        assert rejected["status"] == "DRAFT", (
            "FAA rejection loops the package back to DRAFT")
        assert get_regulatory_package(package["id"])["status"] == "DRAFT"

    def test_faa_tracking_number_retained_across_resubmits(self, api):
        """PRD §3.6: "Submitting an `STC` package moves it from `DRAFT` to `CONFORMITY_REVIEW`; submitting a `FIELD_APPROVAL` package moves it from `DRAFT` to `FAA_SUBMITTED` and mints an `faa_tracking_number` on that first submission, a number retained unchanged across any later resubmissions."
        PRD §3.6: "A `decision` of `APPROVED` moves the package from `CONFORMITY_REVIEW` or `FAA_SUBMITTED` into the terminal `APPROVED` state and stamps `decided_by_user_id` with the acting inspector's `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/regulatory_faa_rejection_cycle
        """
        bundle = setup_approved_work_order(customer_name="FAA Owner",
                                           customer_email="faa@x.com",
                                           equipment_list=[])
        package = create_regulatory_package(bundle["work_order"]["id"],
                                            approval_path="FIELD_APPROVAL")
        first = submit_package(package["id"])
        record_package_decision(package["id"], "REJECTED", inspector_id="insp-1")
        resubmitted = submit_package(package["id"])
        assert resubmitted["status"] == "FAA_SUBMITTED"
        assert resubmitted["faa_tracking_number"] == first["faa_tracking_number"], (
            "the minted tracking number is retained unchanged on resubmission")

        approved = record_package_decision(package["id"], "APPROVED",
                                           inspector_id="insp-1")
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "insp-1"


class TestStcConformityCycle:
    def test_stc_rejection_loops_without_tracking_number(self, api):
        """PRD §3.6: "It begins in `DRAFT`, with `faa_tracking_number` null on the STC path and `decided_by_user_id` null until a decision lands."
        PRD §3.6: "A `decision` of `REJECTED` sends the package back to `DRAFT` — the conformity-rejection loop for STC data, the FAA-rejection loop for field approvals — where the data is corrected in place and resubmitted through the same path-dependent submission."

        Design: Corner/state_machines/stc_conformity_rejection_loops_to_draft
        """
        bundle = setup_approved_work_order(customer_name="STC Stan",
                                           customer_email="s2@x.com",
                                           equipment_list=[])
        package = create_regulatory_package(bundle["work_order"]["id"],
                                            approval_path="STC",
                                            stc_number="STC-SA6666")
        assert_regulatory_package(package)
        first = submit_package(package["id"])
        assert first["status"] == "CONFORMITY_REVIEW"
        assert first["faa_tracking_number"] is None, (
            "no tracking number is ever minted on the STC path")

        rejected = record_package_decision(package["id"], "REJECTED",
                                           inspector_id="insp-1")
        assert rejected["status"] == "DRAFT"
        resubmitted = submit_package(package["id"])
        assert resubmitted["status"] == "CONFORMITY_REVIEW", (
            "resubmission re-enters conformity review on the STC path")
        assert resubmitted["faa_tracking_number"] is None


class TestPackageGates:
    def test_record_decision_from_draft_rejected(self, api):
        """PRD §3.6: "A `decision` of `APPROVED` moves the package from `CONFORMITY_REVIEW` or `FAA_SUBMITTED` into the terminal `APPROVED` state and stamps `decided_by_user_id` with the acting inspector's `X-User-ID`."
        PRD §2.11: "Fifth is state validity with `ERR_INVALID_STATE`: the target entity must sit in a valid from-state for the requested transition, which also covers terminal lockdown and actions attempted on superseded designs."

        Design: Corner/state_machines/record_decision_from_draft_rejected
        """
        bundle = setup_pending_approval(customer_name="Pkg Pat",
                                        customer_email="p3@x.com",
                                        equipment_list=[])
        package = create_regulatory_package(bundle["work_order"]["id"],
                                            approval_path="STC",
                                            stc_number="STC-SA5555")
        response = api.record_decision(package["id"], "APPROVED",
                                       make_inspector_headers("insp-1"))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_regulatory_package(package["id"])["status"] == "DRAFT"

    def test_stc_package_missing_number_rejected(self, api):
        """PRD §3.6: "The `stc_number` is required exactly when the path is `STC`; a missing number on that path is rejected with `ERR_STC_NUMBER_REQUIRED` (HTTP 400)."

        Design: Corner/errors/package_create_stc_missing_stc_number
        """
        bundle = setup_pending_approval(customer_name="Stc Sam",
                                        customer_email="s3@x.com",
                                        equipment_list=[])
        response = api.create_regulatory_package(
            {"work_order_id": bundle["work_order"]["id"], "approval_path": "STC"},
            MANAGER)
        validate_error(response, ApiErrorId.ERR_STC_NUMBER_REQUIRED)

    def test_second_package_rejected(self, api):
        """PRD §3.6: "One package per work order is the rule, and a second attempt draws `ERR_PACKAGE_ALREADY_EXISTS`."

        Design: Corner/errors/package_already_exists
        """
        bundle = setup_pending_approval(customer_name="OnePkg Olga",
                                        customer_email="o@x.com",
                                        equipment_list=[])
        create_regulatory_package(bundle["work_order"]["id"], approval_path="STC",
                                  stc_number="STC-SA1234")
        response = api.create_regulatory_package(
            {"work_order_id": bundle["work_order"]["id"],
             "approval_path": "FIELD_APPROVAL"},
            MANAGER)
        validate_error(response, ApiErrorId.ERR_PACKAGE_ALREADY_EXISTS)
        packages, meta = validate_paginated(
            api.list_regulatory_packages(
                MANAGER, params={"work_order_id": bundle["work_order"]["id"]}))
        assert len(packages) == 1 and meta["total_count"] == 1
