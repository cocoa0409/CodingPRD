"""Distributors: territory admission, installation training, channel standing."""

import lookup
import response
import validate
from db import base_row, bump, by_key, db
from errors import (ERR_DISTRIBUTOR_STATE_INVALID, ERR_DUPLICATE_RESOURCE_CODE,
                    ERR_TECHNICIAN_DISTRIBUTOR_MISMATCH,
                    ERR_TERRITORY_EXCLUSIVITY_CONFLICT,
                    ERR_TRAINING_RECORD_DUPLICATE, fail)
from middleware import (CHANNEL_MANAGER, DISTRIBUTOR, PRODUCT_ENGINEER,
                        TRAINING_ADMINISTRATOR, WARRANTY_ANALYST, endpoint)
from validate import CODE_RE

DISTRIBUTOR_STATES = ["PENDING_TRAINING", "AUTHORIZED", "PROBATION", "TERMINATED"]
TRAINING_MODULES = ["INSTALLATION", "PAYMENT_SYSTEMS", "DIAGNOSTICS"]
LIVE_STATES = ("PENDING_TRAINING", "AUTHORIZED", "PROBATION")


def _distinct_technicians(keys):
    return {key.split("|", 1)[0] for key in keys}


def _modules(keys):
    return {key.split("|", 1)[1] for key in keys if "|" in key}


def register(app):
    @app.post("/clm/distributors")
    @endpoint([CHANNEL_MANAGER])
    def create_distributor():
        body = validate.parse_body()
        distributor_code = body.code("distributor_code")
        legal_name = body.string("legal_name", 1, 160)
        territory_code = body.string("territory_code", 1, 16, pattern=CODE_RE)
        territory_exclusive = body.boolean("territory_exclusive", required=False,
                                           default=False)
        # rule 48: natural-key uniqueness
        if any(d["distributor_code"] == distributor_code
               for d in db.distributors.values()):
            fail(ERR_DUPLICATE_RESOURCE_CODE,
                 "distributor_code '%s' already exists." % distributor_code)
        # rule 51: territory exclusivity, enforced in both directions
        for other in db.distributors.values():
            if other["distributor_state"] not in LIVE_STATES:
                continue
            if other["territory_code"] != territory_code:
                continue
            if territory_exclusive:
                fail(ERR_TERRITORY_EXCLUSIVITY_CONFLICT,
                     "Territory '%s' is already held." % territory_code)
            if other["territory_exclusive"]:
                fail(ERR_TERRITORY_EXCLUSIVITY_CONFLICT,
                     "Territory '%s' is held exclusively." % territory_code)

        row = base_row()
        row.update({
            "distributor_code": distributor_code,
            "legal_name": legal_name,
            "territory_code": territory_code,
            "territory_exclusive": territory_exclusive,
            "completed_training_keys": [],
            "trained_technician_count": 0,
            "installation_training_state": "NOT_STARTED",
            "distributor_state": "PENDING_TRAINING",
            "probation_reason": "NONE",
            "warranty_credit_cents": 0,
            "open_claim_count": 0,
        })
        db.distributors[row["id"]] = row
        return response.created(row)

    @app.get("/clm/distributors/<distributor_id>")
    @endpoint([CHANNEL_MANAGER, TRAINING_ADMINISTRATOR, WARRANTY_ANALYST,
               PRODUCT_ENGINEER, DISTRIBUTOR])
    def read_distributor(distributor_id):
        return response.ok(lookup.distributor(distributor_id))

    @app.get("/clm/distributors")
    @endpoint([CHANNEL_MANAGER, TRAINING_ADMINISTRATOR, WARRANTY_ANALYST])
    def list_distributors():
        limit, offset = validate.q_pagination()
        territory_code = validate.q_str("territory_code")
        distributor_state = validate.q_enum("distributor_state", DISTRIBUTOR_STATES)
        rows = list(db.distributors.values())
        if territory_code is not None:
            rows = [r for r in rows if r["territory_code"] == territory_code]
        if distributor_state is not None:
            rows = [r for r in rows if r["distributor_state"] == distributor_state]
        rows = by_key(rows, "distributor_code")
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/distributors/<distributor_id>/training-completions")
    @endpoint([TRAINING_ADMINISTRATOR])
    def record_training_completion(distributor_id):
        body = validate.parse_body()
        technician_id = body.id_ref("technician_id")
        training_module = body.enum("training_module", TRAINING_MODULES)
        body.date_string("completed_on")
        distributor = lookup.distributor(distributor_id)   # rule 12
        technician = lookup.technician(technician_id)      # rule 20
        # rule 29
        if distributor["distributor_state"] != "PENDING_TRAINING":
            fail(ERR_DISTRIBUTOR_STATE_INVALID,
                 "Training completions require distributor_state PENDING_TRAINING.")
        # rule 41
        if (technician["employer"] != "DISTRIBUTOR"
                or technician["distributor_id"] != distributor["id"]):
            fail(ERR_TECHNICIAN_DISTRIBUTOR_MISMATCH,
                 "The technician is not employed by this distributor.")
        # rule 52
        key = "%s|%s" % (technician["id"], training_module)
        if key in distributor["completed_training_keys"]:
            fail(ERR_TRAINING_RECORD_DUPLICATE,
                 "That technician already completed the %s module." % training_module)

        distributor["completed_training_keys"] = (
            distributor["completed_training_keys"] + [key])
        keys = distributor["completed_training_keys"]
        distributor["trained_technician_count"] = len(_distinct_technicians(keys))
        distributor["installation_training_state"] = "IN_PROGRESS"
        modules = _modules(keys)
        if (len(_distinct_technicians(keys)) >= 2
                and "INSTALLATION" in modules and "PAYMENT_SYSTEMS" in modules):
            distributor["distributor_state"] = "AUTHORIZED"
            distributor["installation_training_state"] = "COMPLETE"
        bump(distributor)
        return response.ok(distributor)

    @app.post("/clm/distributors/<distributor_id>/status-actions")
    @endpoint([CHANNEL_MANAGER])
    def distributor_status_action(distributor_id):
        body = validate.parse_body()
        action = body.enum("action", ["PROBATION", "REINSTATE", "TERMINATE"])
        reason = None
        if action == "PROBATION":
            reason = body.enum("reason", ["WARRANTY_ABUSE", "MANUAL"])
        elif action == "TERMINATE":
            body.string("reason", maxlen=500)
        distributor = lookup.distributor(distributor_id)
        state = distributor["distributor_state"]
        # rule 29: a TERMINATED distributor accepts nothing at all
        if action == "PROBATION" and state != "AUTHORIZED":
            fail(ERR_DISTRIBUTOR_STATE_INVALID,
                 "A probation action requires distributor_state AUTHORIZED.")
        if action == "REINSTATE" and state != "PROBATION":
            fail(ERR_DISTRIBUTOR_STATE_INVALID,
                 "A reinstatement requires distributor_state PROBATION.")
        if action == "TERMINATE" and state not in ("AUTHORIZED", "PROBATION"):
            fail(ERR_DISTRIBUTOR_STATE_INVALID,
                 "A termination requires distributor_state AUTHORIZED or PROBATION.")

        if action == "PROBATION":
            distributor["distributor_state"] = "PROBATION"
            distributor["probation_reason"] = reason
        elif action == "REINSTATE":
            distributor["distributor_state"] = "AUTHORIZED"
            distributor["probation_reason"] = "NONE"
        else:
            distributor["distributor_state"] = "TERMINATED"
        bump(distributor)
        return response.ok(distributor)
