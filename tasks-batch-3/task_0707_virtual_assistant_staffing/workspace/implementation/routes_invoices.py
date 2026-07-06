"""Invoice generation: dual-variant tiered pricing + SLA credit (PRD §3.8)."""
from flask import request


def register_invoice_routes(ctx):
    app = ctx["app"]
    P = ctx["PREFIX"]
    db = ctx["db"]
    stamp_create = ctx["stamp_create"]
    err = ctx["err"]
    ok = ctx["ok"]
    auth = ctx["auth"]
    require_role = ctx["require_role"]
    get_json = ctx["get_json"]
    require_fields = ctx["require_fields"]
    S = ctx["S"]
    svc = ctx["svc"]
    own = ctx["own"]
    calc = ctx["calc"]
    sla_mod = ctx["sla_mod"]
    fk = ctx["fk"]
    list_response = ctx["list_response"]
    get_invoice = ctx["get_invoice"]

    @app.post(f"{P}/invoices")
    def invoice_create():
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        body = get_json(request)
        require_fields(body, ["client_id", "cycle_id", "variant"])
        client_id = body["client_id"]
        cycle_id = body["cycle_id"]
        variant = body["variant"]
        client = fk(db.clients, client_id, "client_id")
        cycle = fk(db.retainer_cycles, cycle_id, "cycle_id")
        if variant not in ("PROVISIONAL", "FINAL"):
            raise err("ERR_INVALID_REQUEST", "variant must be PROVISIONAL|FINAL")
        # Priority 19: variant vs cycle state.
        if variant == "FINAL" and cycle["status"] != "CLOSED":
            raise err("ERR_INVOICE_VARIANT_STATE", "FINAL requires a CLOSED cycle")
        if variant == "PROVISIONAL" and cycle["status"] != "OPEN":
            raise err("ERR_INVOICE_VARIANT_STATE", "PROVISIONAL requires an OPEN cycle")

        result = _price_invoice(ctx, client, cycle, variant)
        rec = {
            "client_id": client_id,
            "cycle_id": cycle_id,
            "variant": variant,
            "status": "ISSUED",
            **result,
        }
        stamp_create(rec)
        db.invoices[rec["id"]] = rec
        return ok(S.invoice(rec), 201)

    @app.get(f"{P}/invoices/<invoice_id>")
    def invoice_get(invoice_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        rec = get_invoice(invoice_id)
        own.require_client_owner(role, uid, rec["client_id"])
        return ok(S.invoice(rec))

    @app.get(f"{P}/invoices")
    def invoice_list():
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        recs = list(db.invoices.values())
        cid = request.args.get("client_id")
        if cid is not None:
            recs = [r for r in recs if r["client_id"] == cid]
        cyid = request.args.get("cycle_id")
        if cyid is not None:
            recs = [r for r in recs if r["cycle_id"] == cyid]
        variant = request.args.get("variant")
        if variant is not None:
            recs = [r for r in recs if r["variant"] == variant]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        if role == "Client":
            recs = [r for r in recs if r["client_id"] == uid]
        return list_response(recs, S.invoice)


def _price_invoice(ctx, client, cycle, variant):
    """Pinned evaluation order (calc invoice_total + sla_breach_credit)."""
    db = ctx["db"]
    calc = ctx["calc"]
    sla_mod = ctx["sla_mod"]
    S = ctx["S"]

    from decimal import Decimal
    def D(x):
        return Decimal(str(x))

    # (1) billed-hour set per variant: entries pinned to this cycle.
    if variant == "PROVISIONAL":
        counted = [te for te in db.time_entries.values()
                   if te.get("cycle_id") == cycle["id"] and te["status"] in ("LOGGED", "APPROVED")]
    else:  # FINAL
        counted = [te for te in db.time_entries.values()
                   if te.get("cycle_id") == cycle["id"] and te["status"] == "APPROVED"]

    billed_hours = sum(D(te["billable_hours"]) for te in counted) if counted else D("0")
    bank = D(cycle["granted_hours"]) + D(cycle["rolled_in_hours"])

    # (2) split into within-bank vs overage tiers.
    within_bank = min(billed_hours, bank)
    overage = billed_hours - bank
    if overage < 0:
        overage = D("0")

    # (3) price each tier, round-per-tier-then-sum (PINNED).
    base_charge = calc.round_cents(within_bank * D(client["base_rate_cents"]))
    overage_charge = calc.round_cents(overage * D(client["overage_rate_cents"]))

    # (4) surcharge: counted entries whose task.required_skill_tag_id matches an
    #     ACTIVE add-on's skill_tag_id on the engagement; priced at that rate.
    surcharge_sum = D("0")
    for te in counted:
        task = db.tasks.get(te["task_id"])
        if task is None:
            continue
        rsid = task.get("required_skill_tag_id")
        if rsid is None:
            continue
        eng_id = task.get("engagement_id")
        addon = None
        for a in db.addons.values():
            if (a["status"] == "ACTIVE" and a["skill_tag_id"] == rsid
                    and a["engagement_id"] == eng_id):
                addon = a
                break
        if addon is not None:
            surcharge_sum += D(te["billable_hours"]) * D(addon["surcharge_rate_cents"])
    surcharge_cents = calc.round_cents(surcharge_sum)

    # (5) SLA breach credit (calc sla_breach_credit): tasks of this client with
    #     >=1 APPROVED entry charged to this cycle AND sla_state RESOLUTION_BREACHED.
    approved_task_ids = {
        te["task_id"] for te in db.time_entries.values()
        if te.get("cycle_id") == cycle["id"] and te["status"] == "APPROVED"
    }
    credit_sum = D("0")
    for task in db.tasks.values():
        if task["client_id"] != client["id"]:
            continue
        if task["id"] not in approved_task_ids:
            continue
        if S.sla_state(task) != "RESOLUTION_BREACHED":
            continue
        policy = sla_mod.sla_policy_for(task["priority"])
        if policy is None:
            continue
        billed = S.task_billed_hours(task)
        credit_sum += D(billed) * D(client["base_rate_cents"]) * D(policy["breach_penalty_pct"])
    sla_credit_cents = calc.round_cents(credit_sum)

    # (6) total floored at 0.
    total = base_charge + overage_charge + surcharge_cents - sla_credit_cents
    if total < 0:
        total = 0

    # utilization = billed_hours / bank, 4dp half-up.
    if bank == 0:
        utilization = float(calc.round_half_up(D("0"), 4))
    else:
        utilization = float(calc.round_half_up(billed_hours / bank, 4))

    return {
        "base_charge_cents": base_charge,
        "overage_charge_cents": overage_charge,
        "surcharge_cents": surcharge_cents,
        "sla_credit_cents": sla_credit_cents,
        "total_cents": total,
        "utilization_pct": utilization,
    }
