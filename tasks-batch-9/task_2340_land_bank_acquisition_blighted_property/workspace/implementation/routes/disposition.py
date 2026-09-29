"""Applicants, disposition applications, screenings and development agreements."""
import calculations as calc
import serializers as ser
import services as svc
from db import base_record, db, now, ordered, touch
from errors import ApiError, bad_request
from middleware import authenticate
from response import list_response, object_response
from validation import (field_bool, field_datetime, field_enum, field_int,
                        field_str, get_body, paginate, present, query_enum,
                        query_str)

APPLICATION_STATUSES = (
    "DRAFT", "SUBMITTED", "SCREENED", "INFO_REQUESTED", "SUSPENDED_TITLE",
    "RECOMMENDED", "BOARD_APPROVED", "BOARD_DENIED", "DENIED", "AWARDED",
)


def register(app):
    # --------------------------------------------------------- applicants ---
    @app.route("/land-bank/applicants", methods=["POST"])
    def create_applicant():
        authenticate("DispositionOfficer")
        body = get_body()
        legal_name = field_str(body, "legal_name", max_len=160)
        applicant_type = field_enum(body, "applicant_type",
                                    ("INDIVIDUAL", "NONPROFIT", "DEVELOPER"))
        contact_email = field_str(body, "contact_email")
        if "@" not in contact_email:
            raise bad_request("Field 'contact_email' must contain an at-sign.")
        registration_no = field_str(body, "nonprofit_registration_no", required=False)
        record = base_record()
        record.update({
            "legal_name": legal_name,
            "applicant_type": applicant_type,
            "contact_email": contact_email,
            "nonprofit_registration_no": registration_no,
            "reverter_count": 0,
            "last_reverter_at": None,
            "good_standing_count": 0,
            "delinquent_tax_total_cents": 0,
            "open_code_violation_total": 0,
            "recent_reverter_count": 0,
            "conveyed_property_count": 0,
            "eligibility_status": "ELIGIBLE",
        })
        db.applicants[record["id"]] = record
        return object_response(ser.applicant_out(record), 201)

    @app.route("/land-bank/applicants/<applicant_id>", methods=["GET"])
    def read_applicant(applicant_id):
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "CountyTreasurer", "Applicant")
        applicant = svc.get_applicant(applicant_id)
        return object_response(ser.applicant_out(applicant))

    # ------------------------------------------------------- applications ---
    @app.route("/land-bank/disposition-applications", methods=["POST"])
    def create_application():
        user_id, role = authenticate("DispositionOfficer", "Applicant")
        body = get_body()
        raw_applicant = body.get("applicant_id")
        if role == "Applicant" and isinstance(raw_applicant, str) \
                and raw_applicant != user_id:
            raise ApiError("ERR_NOT_APPLICATION_OWNER")
        property_id = field_str(body, "property_id")
        applicant_id = field_str(body, "applicant_id")
        program = field_enum(body, "program", calc.PROGRAMS)
        proposed_use = field_str(body, "proposed_use", max_len=500)
        offer_price = field_int(body, "offer_price_cents", minimum=0)
        if role == "Applicant" and applicant_id != user_id:
            raise ApiError("ERR_NOT_APPLICATION_OWNER")
        prop = svc.get_property(property_id)
        applicant = svc.get_applicant(applicant_id)
        record = base_record()
        record.update({
            "property_id": prop["id"],
            "applicant_id": applicant["id"],
            "program": program,
            "proposed_use": proposed_use,
            "offer_price_cents": offer_price,
            "quoted_price_cents": calc.quoted_price_cents(prop, program),
            "status": "DRAFT",
            "revision_round": 0,
            "submitted_at": None,
            "screening_count": 0,
            "suspended_from_status": None,
            "recommended_by_user_id": None,
            "recommendation_memo": None,
            "decided_by_user_id": None,
            "board_decision_at": None,
            "denial_reason": None,
            "_information_requested": None,
        })
        db.applications[record["id"]] = record
        return object_response(ser.application_out(record), 201)

    @app.route("/land-bank/disposition-applications/<application_id>",
               methods=["GET"])
    def read_application(application_id):
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "CountyTreasurer", "Applicant")
        application = svc.get_application(application_id)
        return object_response(ser.application_out(application))

    @app.route("/land-bank/disposition-applications", methods=["GET"])
    def list_applications():
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "CountyTreasurer")
        property_id = query_str("property_id")
        applicant_id = query_str("applicant_id")
        status = query_enum("status", APPLICATION_STATUSES)
        program = query_enum("program", calc.PROGRAMS)
        records = ordered(list(db.applications.values()))
        if property_id is not None:
            records = [r for r in records if r["property_id"] == property_id]
        if applicant_id is not None:
            records = [r for r in records if r["applicant_id"] == applicant_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        if program is not None:
            records = [r for r in records if r["program"] == program]
        items, meta = paginate(records, ser.application_out)
        return list_response(items, meta)

    def _owned_application(application_id, user_id, role):
        application = db.applications.get(application_id)
        if application is not None and role == "Applicant" \
                and application["applicant_id"] != user_id:
            raise ApiError("ERR_NOT_APPLICATION_OWNER")
        if application is None:
            raise ApiError("ERR_APPLICATION_NOT_FOUND")
        return application

    @app.route("/land-bank/disposition-applications/<application_id>/submit",
               methods=["POST"])
    def submit_application(application_id):
        user_id, role = authenticate("Applicant")
        application = _owned_application(application_id, user_id, role)
        if application["status"] != "DRAFT":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        prop = svc.get_property(application["property_id"])
        applicant = svc.get_applicant(application["applicant_id"])
        quote = svc.run_submit_gate(
            application, prop, applicant, application["offer_price_cents"], False
        )
        application["status"] = "SUBMITTED"
        application["submitted_at"] = now()
        application["quoted_price_cents"] = quote
        touch(application)
        return object_response(ser.application_out(application))

    @app.route("/land-bank/disposition-applications/<application_id>/screen",
               methods=["POST"])
    def screen_application(application_id):
        user_id, _role = authenticate("DispositionOfficer")
        application = svc.get_application(application_id)
        if application["status"] != "SUBMITTED":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        prop = svc.get_property(application["property_id"])
        applicant = svc.get_applicant(application["applicant_id"])
        result = svc.evaluate_screening(application, prop, applicant)
        rollup = result["rollup"]
        record = base_record(versioned=False)
        record.update({
            "application_id": application["id"],
            "sequence_no": application["screening_count"] + 1,
            "screened_by_user_id": user_id,
            "screened_at": now(),
            "delinquent_tax_total_cents": rollup["delinquent_tax_total_cents"],
            "open_code_violation_total": rollup["open_code_violation_total"],
            "recent_reverter_count": rollup["recent_reverter_count"],
            "disqualifiers": result["disqualifiers"],
            "eligibility_score": result["eligibility_score"],
            "outcome": result["outcome"],
        })
        db.screenings[record["id"]] = record
        application["screening_count"] = application["screening_count"] + 1
        if result["outcome"] == "PASS":
            application["status"] = "SCREENED"
        else:
            application["status"] = "DENIED"
            application["denial_reason"] = "SCREENING_FAIL:" + result["disqualifiers"][0]
        touch(application)
        return object_response(ser.screening_out(record), 201)

    @app.route("/land-bank/disposition-applications/<application_id>/screenings",
               methods=["GET"])
    def list_screenings(application_id):
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "Applicant")
        outcome = query_enum("outcome", ("PASS", "FAIL"))
        application = svc.get_application(application_id)
        records = svc.screenings_of(application["id"])
        if outcome is not None:
            records = [r for r in records if r["outcome"] == outcome]
        items, meta = paginate(records, ser.screening_out)
        return list_response(items, meta)

    @app.route("/land-bank/disposition-applications/<application_id>/request-info",
               methods=["POST"])
    def request_info(application_id):
        authenticate("DispositionOfficer")
        body = get_body()
        information_requested = field_str(body, "information_requested", max_len=1000)
        application = svc.get_application(application_id)
        if application["status"] not in ("SUBMITTED", "SCREENED"):
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        application["suspended_from_status"] = application["status"]
        application["status"] = "INFO_REQUESTED"
        application["_information_requested"] = information_requested
        touch(application)
        return object_response(ser.application_out(application))

    @app.route("/land-bank/disposition-applications/<application_id>/resubmit",
               methods=["POST"])
    def resubmit_application(application_id):
        user_id, role = authenticate("Applicant")
        body = get_body()
        offer_price = field_int(body, "offer_price_cents", required=False, minimum=0)
        proposed_use = field_str(body, "proposed_use", required=False, max_len=500)
        application = _owned_application(application_id, user_id, role)
        if application["status"] != "INFO_REQUESTED":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        prop = svc.get_property(application["property_id"])
        applicant = svc.get_applicant(application["applicant_id"])
        effective_offer = (offer_price if offer_price is not None
                           else application["offer_price_cents"])
        quote = svc.run_submit_gate(application, prop, applicant,
                                    effective_offer, True)
        if offer_price is not None:
            application["offer_price_cents"] = offer_price
        if proposed_use is not None:
            application["proposed_use"] = proposed_use
        application["status"] = "SUBMITTED"
        application["revision_round"] = application["revision_round"] + 1
        application["submitted_at"] = now()
        application["quoted_price_cents"] = quote
        application["suspended_from_status"] = None
        touch(application)
        return object_response(ser.application_out(application))

    @app.route("/land-bank/disposition-applications/<application_id>/recommend",
               methods=["POST"])
    def recommend_application(application_id):
        user_id, _role = authenticate("DispositionOfficer")
        body = get_body()
        memo = field_str(body, "recommendation_memo", max_len=1000)
        application = svc.get_application(application_id)
        if application["status"] != "SCREENED":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        prop = svc.get_property(application["property_id"])
        if prop["title_status"] != "CLEAR":
            raise ApiError("ERR_TITLE_NOT_CLEAR")
        if prop["custody_status"] != "LISTED":
            raise ApiError("ERR_PROPERTY_NOT_LISTED")
        screening = svc.governing_screening(application["id"])
        if screening is None or screening["outcome"] != "PASS":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        if user_id == screening["screened_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        application["status"] = "RECOMMENDED"
        application["recommendation_memo"] = memo
        application["recommended_by_user_id"] = user_id
        touch(application)
        return object_response(ser.application_out(application))

    @app.route("/land-bank/disposition-applications/<application_id>/board-decision",
               methods=["POST"])
    def board_decision(application_id):
        user_id, _role = authenticate("BoardClerk")
        body = get_body()
        decision = field_enum(body, "decision", ("APPROVE", "DENY"))
        resolution_no = field_str(body, "resolution_no")
        denial_reason = field_str(body, "denial_reason", required=False, max_len=500)
        application = svc.get_application(application_id)
        if application["status"] != "RECOMMENDED":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        prop = svc.get_property(application["property_id"])
        if decision == "APPROVE" and prop["custody_status"] != "LISTED":
            raise ApiError("ERR_PROPERTY_NOT_LISTED")
        application["status"] = ("BOARD_APPROVED" if decision == "APPROVE"
                                else "BOARD_DENIED")
        application["decided_by_user_id"] = user_id
        application["board_decision_at"] = now()
        application["_resolution_no"] = resolution_no
        if decision == "DENY":
            application["denial_reason"] = denial_reason
        touch(application)
        return object_response(ser.application_out(application))

    # ------------------------------------------------ development agreements --
    @app.route("/land-bank/development-agreements", methods=["POST"])
    def create_agreement():
        authenticate("BoardClerk")
        body = get_body()
        application_id = field_str(body, "application_id")
        performance_deadline = field_datetime(body, "performance_deadline")
        milestone_count = field_int(body, "milestone_count", minimum=1)
        reverter_active = field_bool(body, "reverter_clause_active")
        abatement_years = field_int(body, "abatement_years")
        discharge_mode = field_enum(body, "discharge_mode",
                                    ("STATUTORY", "NEGOTIATED"))
        projected_value = field_int(body, "projected_improved_value_cents",
                                    minimum=0)
        application = svc.get_application(application_id)
        for existing in db.agreements.values():
            if existing["application_id"] == application["id"]:
                raise ApiError("ERR_AGREEMENT_ALREADY_EXISTS")
        if application["status"] != "BOARD_APPROVED":
            raise ApiError("ERR_APPLICATION_INVALID_STATE")
        prop = svc.get_property(application["property_id"])
        if prop["custody_status"] != "LISTED":
            raise ApiError("ERR_PROPERTY_NOT_LISTED")
        if performance_deadline <= now():
            raise ApiError("ERR_DEADLINE_IN_PAST")
        if abatement_years < 0 or abatement_years > calc.MAX_ABATEMENT_YEARS:
            raise ApiError("ERR_ABATEMENT_YEARS_EXCEED_CAP")

        applicant = svc.get_applicant(application["applicant_id"])
        sale_price = application["offer_price_cents"]
        relief = calc.tax_discharge_and_abatement(
            prop, discharge_mode, sale_price, projected_value, abatement_years
        )
        record = base_record()
        record.update({
            "application_id": application["id"],
            "property_id": prop["id"],
            "performance_deadline": performance_deadline,
            "cure_deadline": None,
            "milestone_count": milestone_count,
            "milestones_completed": 0,
            "reverter_clause_active": reverter_active,
            "abatement_years": abatement_years,
            "discharge_mode": discharge_mode,
            "projected_improved_value_cents": projected_value,
            "sale_price_cents": sale_price,
            "discharged_tax_cents": relief["discharged_tax_cents"],
            "abatement_annual_cents": relief["abatement_annual_cents"],
            "abatement_total_cents": relief["abatement_total_cents"],
            "status": "EXECUTED",
            "executed_at": now(),
            "complied_at": None,
            "reverted_at": None,
        })
        db.agreements[record["id"]] = record

        prop["delinquent_tax_balance_cents"] = max(
            0, prop["delinquent_tax_balance_cents"] - relief["discharged_tax_cents"]
        )
        prop["custody_status"] = "CONVEYED"
        prop["owner_of_record_applicant_id"] = applicant["id"]
        touch(prop)
        application["status"] = "AWARDED"
        touch(application)
        svc.refresh_applicant(applicant)
        return object_response(ser.agreement_out(record), 201)

    @app.route("/land-bank/development-agreements/<agreement_id>",
               methods=["GET"])
    def read_agreement(agreement_id):
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "CountyTreasurer", "Applicant")
        agreement = svc.get_agreement(agreement_id)
        return object_response(ser.agreement_out(agreement))

    @app.route("/land-bank/development-agreements", methods=["GET"])
    def list_agreements():
        authenticate("IntakeOfficer", "BoardClerk", "DispositionOfficer",
                     "CountyTreasurer")
        application_id = query_str("application_id")
        property_id = query_str("property_id")
        status = query_enum("status", ("EXECUTED", "CURE_PENDING", "COMPLIED",
                                       "REVERTED"))
        records = ordered(list(db.agreements.values()))
        if application_id is not None:
            records = [r for r in records if r["application_id"] == application_id]
        if property_id is not None:
            records = [r for r in records if r["property_id"] == property_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, meta = paginate(records, ser.agreement_out)
        return list_response(items, meta)

    @app.route("/land-bank/development-agreements/<agreement_id>/milestone-completions",
               methods=["POST"])
    def report_milestones(agreement_id):
        user_id, role = authenticate("Applicant")
        body = get_body()
        completed_count = field_int(body, "completed_count", minimum=0)
        field_str(body, "evidence_reference", max_len=500)
        agreement = db.agreements.get(agreement_id)
        if agreement is not None and role == "Applicant":
            application = db.applications.get(agreement["application_id"])
            if application is None or application["applicant_id"] != user_id:
                raise ApiError("ERR_NOT_APPLICATION_OWNER")
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")
        if agreement["status"] not in ("EXECUTED", "CURE_PENDING"):
            raise ApiError("ERR_AGREEMENT_INVALID_STATE")
        if agreement["milestones_completed"] + completed_count > agreement["milestone_count"]:
            raise ApiError("ERR_MILESTONE_OVERFLOW")

        from_status = agreement["status"]
        agreement["milestones_completed"] = (
            agreement["milestones_completed"] + completed_count
        )
        if agreement["milestones_completed"] == agreement["milestone_count"]:
            if from_status == "EXECUTED":
                deadline = agreement["performance_deadline"]
            else:
                deadline = agreement["cure_deadline"]
            if deadline is not None and now() <= deadline:
                agreement["status"] = "COMPLIED"
                agreement["complied_at"] = now()
                agreement["reverter_clause_active"] = False
                application = db.applications.get(agreement["application_id"])
                if application is not None:
                    applicant = db.applicants.get(application["applicant_id"])
                    if applicant is not None:
                        applicant["good_standing_count"] = (
                            applicant["good_standing_count"] + 1
                        )
                        touch(applicant)
        touch(agreement)
        return object_response(ser.agreement_out(agreement))
