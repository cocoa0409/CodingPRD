"""Cross-aggregate side effects: slot accounting, custody roll-ups, the
no-show cascade, the discard cascade and the recall walk."""
import store
import calc
import constants as C


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def deliveries_of_lot(lot):
    return store.ordered("ShareDelivery", lambda d: d.get("landing_lot_id") == lot["id"])


def deliveries_of_sub_lot(sub_lot):
    return store.ordered("ShareDelivery", lambda d: d.get("sub_lot_id") == sub_lot["id"])


def sub_lots_of(lot):
    return store.ordered("SubLot", lambda s: s["landing_lot_id"] == lot["id"])


def deliveries_of_subscription(sub):
    return store.ordered("ShareDelivery", lambda d: d["subscription_id"] == sub["id"])


def recompute_slots(window):
    """PRD 3.7: slots_free is at all times cooler_slots_total less the
    reserved, occupied and forfeited counts."""
    window["slots_free"] = (window["cooler_slots_total"] - window["slots_reserved"]
                            - window["slots_occupied"] - window["slots_forfeited"])


def release_slot(delivery):
    """PRD 3.7: "Voiding a box that was staged simply releases its reservation,
    lowering slots_reserved by 1"."""
    window = store.get("PickupWindow", delivery.get("pickup_window_id"))
    if window is None:
        return
    window["slots_reserved"] = max(0, window["slots_reserved"] - 1)
    recompute_slots(window)
    store.touch(window)


def member_of_delivery(delivery):
    sub = store.get("Subscription", delivery["subscription_id"])
    return store.get("Member", sub["member_id"]) if sub else None


def add_credit(delivery, amount):
    """Writes both sides of INV_MEMBER_CREDIT in the same step."""
    if amount == 0:
        return 0
    delivery["credit_cents"] = delivery["credit_cents"] + amount
    member = member_of_delivery(delivery)
    if member is not None:
        member["credit_balance_cents"] = member["credit_balance_cents"] + amount
        store.touch(member)
    store.touch(delivery)
    return amount


def cumulative_charged(sub):
    """PRD 3.2: "the sum of charged_cents over this subscription's deliveries
    whose billing_status is CHARGED or PARTIALLY_CREDITED"."""
    total = 0
    for d in deliveries_of_subscription(sub):
        if d["billing_status"] in ("CHARGED", "PARTIALLY_CREDITED"):
            total += d["charged_cents"]
    return total


def arrears_check(sub):
    """PRD 3.7: the installment arrears test, run at pack."""
    if sub["payment_basis"] != "INSTALLMENT":
        return
    if sub["lifecycle_status"] != "ACTIVE":
        return
    if sub["paid_cents"] < cumulative_charged(sub):
        sub["lifecycle_status"] = "PAST_DUE"
        if sub["billing_status"] == "CURRENT":
            sub["billing_status"] = "DUNNING"
        store.touch(sub)


# --------------------------------------------------------------------------
# custody roll-ups
# --------------------------------------------------------------------------

def maybe_dispatch_lot(lot):
    """PRD 3.4: "When no sub-lot of a lot remains IN_TRANSIT, the lot itself
    moves SPLIT -> DISPATCHED"."""
    if lot["status"] != "SPLIT":
        return
    if any(s["status"] == "IN_TRANSIT" for s in sub_lots_of(lot)):
        return
    lot["status"] = "DISPATCHED"
    store.touch(lot)


def maybe_consume_sub_lot(sub_lot):
    if sub_lot is None or sub_lot["status"] != "ARRIVED":
        return
    blocking = ("PACKED", "IN_TRANSIT", "AT_HUB", "NO_SHOW")
    for d in deliveries_of_sub_lot(sub_lot):
        if d["fulfillment_status"] in blocking:
            return
    sub_lot["status"] = "CONSUMED"
    store.touch(sub_lot)


def maybe_close_lot(lot):
    if lot is None or lot["status"] != "DISPATCHED":
        return
    blocking = ("ALLOCATED", "PACKED", "IN_TRANSIT", "AT_HUB", "NO_SHOW")
    for d in deliveries_of_lot(lot):
        if d["fulfillment_status"] in blocking:
            return
    lot["status"] = "CLOSED"
    store.touch(lot)


def settle_custody(delivery):
    """Run the two roll-ups a completed handover can trigger."""
    sub_lot = store.get("SubLot", delivery.get("sub_lot_id"))
    maybe_consume_sub_lot(sub_lot)
    lot = store.get("LandingLot", delivery.get("landing_lot_id"))
    maybe_close_lot(lot)


# --------------------------------------------------------------------------
# the no-show cascade (PRD 3.7), four hops in one request
# --------------------------------------------------------------------------

def no_show_cascade(window):
    staged = store.ordered(
        "ShareDelivery",
        lambda d: d.get("pickup_window_id") == window["id"]
        and d["fulfillment_status"] == "AT_HUB")
    restricted_members = []
    for delivery in staged:
        # hop 1
        delivery["fulfillment_status"] = "NO_SHOW"
        # hop 2, caused by hop 1
        delivery["fulfillment_status"] = "DONATED"
        if delivery["billing_status"] == "CHARGED":
            delivery["billing_status"] = "FORFEITED"
        window["slots_reserved"] = max(0, window["slots_reserved"] - 1)
        window["slots_forfeited"] = window["slots_forfeited"] + 1
        recompute_slots(window)
        store.touch(delivery)
        sub = store.get("Subscription", delivery["subscription_id"])
        member = store.get("Member", sub["member_id"]) if sub else None
        if sub is not None:
            sub["member_fault_count"] = sub["member_fault_count"] + 1
            store.touch(sub)
        if member is not None:
            member["season_no_show_count"] = member["season_no_show_count"] + 1
            # hop 3, caused by the member counter written in hop 2
            new_standing = calc.standing_for(member["season_no_show_count"],
                                             member["standing"])
            member["standing"] = new_standing
            store.touch(member)
            if new_standing == "RESTRICTED" and member["id"] not in restricted_members:
                restricted_members.append(member["id"])
    # hop 4, caused by hop 3
    for member_id in restricted_members:
        for sub in store.ordered("Subscription",
                                 lambda s: s["member_id"] == member_id
                                 and s["lifecycle_status"] == "ACTIVE"):
            sub["lifecycle_status"] = "PAUSED"
            store.touch(sub)


# --------------------------------------------------------------------------
# the discard cascade (PRD 3.6), six hops in one request
# --------------------------------------------------------------------------

def discard_cascade(lot, season):
    """Hop 1 is the disposition itself; this runs hops 2 to 6."""
    # hop 2
    for sub_lot in sub_lots_of(lot):
        if sub_lot["status"] not in ("IN_TRANSIT", "ARRIVED"):
            continue
        sub_lot["status"] = "DESTROYED"
        store.touch(sub_lot)
        # hop 3, caused by hop 2
        for delivery in deliveries_of_sub_lot(sub_lot):
            if delivery["fulfillment_status"] not in (
                    "ALLOCATED", "PACKED", "IN_TRANSIT", "AT_HUB"):
                continue
            was_at_hub = delivery["fulfillment_status"] == "AT_HUB"
            delivery["fulfillment_status"] = "VOIDED"
            delivery["fill_status"] = "VOID"
            store.touch(delivery)
            if was_at_hub:
                release_slot(delivery)
            # hop 4, caused by hop 3
            if delivery["billing_status"] in ("CHARGED", "PARTIALLY_CREDITED"):
                add_credit(delivery,
                           delivery["invoice_total_cents"] - delivery["credit_cents"])
                delivery["billing_status"] = "REFUNDED"
                sub = store.get("Subscription", delivery["subscription_id"])
                if sub is not None:
                    sub["credited_count"] = sub["credited_count"] + 1
                    store.touch(sub)
                    # hop 5, caused by the credited_count written in hop 4
                    if sub["true_up_status"] == "NOT_DUE":
                        sub["true_up_status"] = "SHORTFALL_FLAGGED"
                        # hop 6, caused by hop 5
                        if season is not None:
                            season["shortfall_flag_count"] = \
                                season["shortfall_flag_count"] + 1
                            store.touch(season)


# --------------------------------------------------------------------------
# the recall walk (PRD 3.9), four hops in one request
# --------------------------------------------------------------------------

def recall_walk(lot, notice):
    # hop 1
    lot["status"] = "RECALLED"
    store.touch(lot)

    all_sub_lots = sub_lots_of(lot)
    # hop 2, caused by hop 1
    for sub_lot in all_sub_lots:
        if sub_lot["status"] in ("IN_TRANSIT", "ARRIVED"):
            sub_lot["status"] = "RETURNED"
            store.touch(sub_lot)

    sub_lot_ids = {s["id"] for s in all_sub_lots}
    deliveries = store.ordered("ShareDelivery",
                               lambda d: d.get("sub_lot_id") in sub_lot_ids)

    members = []
    total_credit = 0
    # hop 3 and hop 4
    for delivery in deliveries:
        sub = store.get("Subscription", delivery["subscription_id"])
        if sub is not None and sub["member_id"] not in members:
            members.append(sub["member_id"])
        # Adjudication of friction 5: a delivery whose money axis already stands
        # in REFUNDED or FORFEITED is visited by the walk -- it counts towards
        # impacted_delivery_count and impacted_member_count -- but receives a
        # credit of 0 and no axis change.  PRD 3.9 says so twice ("Deliveries
        # whose money axis already stood in REFUNDED or FORFEITED are visited by
        # the walk and receive nothing") and its terminal fulfillment states
        # (VOIDED, DONATED) declare no onward transition, so the generic
        # "invoice_total_cents less credit_cents" line does not apply to them.
        if delivery["billing_status"] in ("REFUNDED", "FORFEITED"):
            continue
        credit = delivery["invoice_total_cents"] - delivery["credit_cents"]
        if delivery["fulfillment_status"] in ("DELIVERED", "PICKED_UP"):
            delivery["billing_status"] = "CREDITED"
        else:
            was_at_hub = delivery["fulfillment_status"] == "AT_HUB"
            delivery["fulfillment_status"] = "VOIDED"
            delivery["fill_status"] = "VOID"
            if was_at_hub:
                release_slot(delivery)
            # Adjudication of friction 6: the money axis of a recall-voided
            # delivery is left where it stands; only credit_cents moves.  PRD
            # 3.9 names a billing move for the already-received branch only ("a
            # delivery that had already reached DELIVERED or PICKED_UP has its
            # money axis moved to CREDITED"), and the state table gives
            # CHARGED/PARTIALLY_CREDITED -> REFUNDED exclusively to discard
            # cascade hop 4.  Keeping REFUNDED to the discard path is what keeps
            # the two cascades distinguishable on the money axis.
        store.touch(delivery)
        total_credit += add_credit(delivery, credit)

    notice["impacted_sub_lot_count"] = len(all_sub_lots)
    notice["impacted_delivery_count"] = len(deliveries)
    notice["impacted_member_count"] = len(members)
    notice["total_credit_cents"] = total_credit
