"""Composite setup helpers.

The harness restarts the API server before every individual test, so the database
is empty at the start of each one. Every helper here therefore builds its
preconditions from scratch through PRD-declared endpoints only.

Two ordering rules drive the shape of these helpers:

* Onboarding-document submission carries `expected_cook_version`, and every
  submission increments the cook's `version` (PRD 2.6 / 3.1), so the second
  document must be submitted with the version observed *after* the first.
* The reviewer who graded the kitchen-inspection document may not approve that
  cook's menu items (PRD 2.1 segregation of duties), so the inspection is graded
  by `rev-2` and menu items are approved by `rev-1`.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_STARTUP_DEFAULT
from .factories import (
    adjudicate_payload,
    approve_menu_item_payload,
    consolidate_payload,
    cook_payload,
    delivery_zone_payload,
    document_review_payload,
    food_handler_cert_payload,
    kitchen_inspection_payload,
    menu_item_payload,
    onboarding_decision_payload,
    order_advance_payload,
    order_payload,
    payout_statement_payload,
    pickup_hub_payload,
    production_window_payload,
    refund_event_payload,
    safety_incident_payload,
    standing_action_payload,
    state_policy_payload,
    statement_advance_payload,
    triage_payload,
    window_advance_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    DINER_ONE_HEADERS,
    FINANCE_ONE_HEADERS,
    OFFICER_ONE_HEADERS,
    OFFICER_TWO_HEADERS,
    REVIEWER_ONE,
    REVIEWER_ONE_HEADERS,
    REVIEWER_TWO,
    REVIEWER_TWO_HEADERS,
    make_cook_headers,
    make_diner_headers,
)


class Bag(dict):
    """Dict with attribute access so scenarios read like records."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - surfaces a setup mistake
            raise AttributeError(item) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


# ==========================================================================
# Tier 1 — single-entity helpers
# ==========================================================================
def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical UTC clock; a platform administrator's privilege (PRD 2.5)."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN_HEADERS))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Return the clock to the mandatory startup default."""
    return set_clock(api, CLOCK_STARTUP_DEFAULT)


def create_state_policy(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_state_policy(state_policy_payload(**kwargs), ADMIN_HEADERS), 201
    )


def register_cook(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Self-registration is open to unauthenticated visitors (PRD 3.1)."""
    return get_success_data(api.create_cook(cook_payload(**kwargs), ANONYMOUS_HEADERS), 201)


def read_cook(api: ApiClient, cook_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cook(cook_id, ADMIN_HEADERS))


def read_menu_item(api: ApiClient, menu_item_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_menu_item(menu_item_id, ADMIN_HEADERS))


def read_document(api: ApiClient, document_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_onboarding_document(document_id, ADMIN_HEADERS))


def read_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_production_window(window_id, ADMIN_HEADERS))


def read_hub(api: ApiClient, hub_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_pickup_hub(hub_id, ADMIN_HEADERS))


def read_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, ADMIN_HEADERS))


def read_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_safety_incident(incident_id, ADMIN_HEADERS))


def read_statement(api: ApiClient, statement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_payout_statement(statement_id, ADMIN_HEADERS))


def read_refund(api: ApiClient, refund_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_refund_event(refund_id, ADMIN_HEADERS))


def read_compliance_summary(api: ApiClient, cook_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_compliance_summary(cook_id, OFFICER_ONE_HEADERS))


def cook_version(api: ApiClient, cook_id: str) -> int:
    return read_cook(api, cook_id)["version"]


def window_version(api: ApiClient, window_id: str) -> int:
    return read_window(api, window_id)["version"]


def create_delivery_zone(api: ApiClient, state_policy_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_delivery_zone(delivery_zone_payload(state_policy_id, **kwargs), ADMIN_HEADERS),
        201,
    )


def create_pickup_hub(api: ApiClient, delivery_zone_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_pickup_hub(pickup_hub_payload(delivery_zone_id, **kwargs), ADMIN_HEADERS), 201
    )


# ==========================================================================
# Tier 2 — cook onboarding
# ==========================================================================
def submit_food_handler_cert(
    api: ApiClient, cook: Dict[str, Any], expected_version: Optional[int] = None, **kwargs: Any
) -> Dict[str, Any]:
    """Submit the FOOD_HANDLER_CERT document as the owning cook."""
    version = cook["version"] if expected_version is None else expected_version
    return get_success_data(
        api.create_onboarding_document(
            food_handler_cert_payload(cook["id"], version, **kwargs),
            make_cook_headers(cook["id"]),
        ),
        201,
    )


def submit_kitchen_inspection(
    api: ApiClient, cook: Dict[str, Any], expected_version: Optional[int] = None, **kwargs: Any
) -> Dict[str, Any]:
    """Submit the KITCHEN_INSPECTION document as the owning cook."""
    version = cook_version(api, cook["id"]) if expected_version is None else expected_version
    kwargs.setdefault("kitchen_type_claimed", cook.get("claimed_kitchen_type", "HOME_INSPECTED"))
    return get_success_data(
        api.create_onboarding_document(
            kitchen_inspection_payload(cook["id"], version, **kwargs),
            make_cook_headers(cook["id"]),
        ),
        201,
    )


def review_document(
    api: ApiClient,
    document_id: str,
    decision: str,
    reviewer_headers: Optional[Dict[str, str]] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    headers = REVIEWER_ONE_HEADERS if reviewer_headers is None else reviewer_headers
    return get_success_data(
        api.review_onboarding_document(document_id, document_review_payload(decision, note), headers)
    )


def decide_onboarding(
    api: ApiClient,
    cook_id: str,
    decision: str,
    reviewer_headers: Optional[Dict[str, str]] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    headers = REVIEWER_ONE_HEADERS if reviewer_headers is None else reviewer_headers
    return get_success_data(
        api.cook_onboarding_decision(cook_id, onboarding_decision_payload(decision, note), headers)
    )


def onboard_active_cook(
    api: ApiClient,
    state_code: str = "CA",
    policy: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    cook_overrides: Optional[Dict[str, Any]] = None,
    cert_overrides: Optional[Dict[str, Any]] = None,
    inspection_overrides: Optional[Dict[str, Any]] = None,
    inspection_decision: str = "PASS",
    activate: bool = True,
) -> Bag:
    """Drive a cook from self-registration to ACTIVE / CLEAR.

    The kitchen-inspection document is graded by `rev-2` so that `rev-1` remains
    eligible to approve this cook's menu items later.
    """
    if policy is None:
        policy = create_state_policy(api, state_code=state_code, **(policy_overrides or {}))
    cook = register_cook(api, state_code=state_code, **(cook_overrides or {}))
    cert = submit_food_handler_cert(api, cook, **(cert_overrides or {}))
    inspection = submit_kitchen_inspection(api, cook, **(inspection_overrides or {}))
    cert = review_document(api, cert["id"], "VERIFY", REVIEWER_ONE_HEADERS)
    inspection = review_document(api, inspection["id"], inspection_decision, REVIEWER_TWO_HEADERS)
    if activate:
        cook = decide_onboarding(api, cook["id"], "ACTIVATE", REVIEWER_ONE_HEADERS)
    else:
        cook = read_cook(api, cook["id"])
    return Bag(
        policy=policy,
        cook=cook,
        cook_id=cook["id"],
        cook_headers=make_cook_headers(cook["id"]),
        cert_document=cert,
        inspection_document=inspection,
        inspection_reviewer=REVIEWER_TWO,
        menu_reviewer=REVIEWER_ONE,
    )


def suspend_cook(api: ApiClient, cook_id: str, reason: str = "MANUAL_SAFETY_REVIEW") -> Dict[str, Any]:
    return get_success_data(
        api.cook_standing_action(cook_id, standing_action_payload("SUSPEND", reason), OFFICER_ONE_HEADERS)
    )


def reinstate_cook(
    api: ApiClient, cook_id: str, reason: str = "REVIEW_CLOSED_NO_FINDING"
) -> Dict[str, Any]:
    return get_success_data(
        api.cook_standing_action(
            cook_id, standing_action_payload("REINSTATE", reason), OFFICER_ONE_HEADERS
        )
    )


# ==========================================================================
# Tier 2 — menu items
# ==========================================================================
def draft_menu_item(api: ApiClient, cook: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_menu_item(menu_item_payload(cook["id"], **kwargs), make_cook_headers(cook["id"])),
        201,
    )


def submit_menu_item(api: ApiClient, cook_id: str, menu_item_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_menu_item(menu_item_id, make_cook_headers(cook_id)))


def review_menu_item(
    api: ApiClient,
    menu_item_id: str,
    decision: str,
    reviewer_headers: Optional[Dict[str, str]] = None,
    allergen_review_notes: Optional[str] = None,
    revision_note: Optional[str] = None,
) -> Dict[str, Any]:
    from .factories import menu_item_review_payload

    headers = REVIEWER_ONE_HEADERS if reviewer_headers is None else reviewer_headers
    payload = menu_item_review_payload(decision, allergen_review_notes, revision_note)
    return get_success_data(api.review_menu_item(menu_item_id, payload, headers))


def approved_menu_item(api: ApiClient, cook: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Draft -> submit -> approve a menu item, returning the APPROVED representation."""
    item = draft_menu_item(api, cook, **kwargs)
    submit_menu_item(api, cook["id"], item["id"])
    return get_success_data(
        api.review_menu_item(item["id"], approve_menu_item_payload(), REVIEWER_ONE_HEADERS)
    )


# ==========================================================================
# Tier 2 — production windows
# ==========================================================================
def open_production_window(api: ApiClient, cook: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_production_window(
            production_window_payload(cook["id"], **kwargs), make_cook_headers(cook["id"])
        ),
        201,
    )


_WINDOW_ACTOR = {
    "CUTOFF_PASSED": "cook",
    "IN_PRODUCTION": "cook",
    "CLOSED": "finance",
    "CANCELLED": "cook",
}


def advance_window(
    api: ApiClient,
    window: Dict[str, Any],
    to_status: str,
    headers: Optional[Dict[str, str]] = None,
    cancelled_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Advance a window. Windows move under the cook's or the finance operator's hand."""
    if headers is None:
        actor = _WINDOW_ACTOR.get(to_status, "cook")
        headers = (
            FINANCE_ONE_HEADERS if actor == "finance" else make_cook_headers(window["cook_id"])
        )
    payload = window_advance_payload(to_status, cancelled_reason)
    return get_success_data(api.advance_production_window(window["id"], payload, headers))


def cancel_window(
    api: ApiClient, window: Dict[str, Any], cancelled_reason: str = "COOK_REQUEST"
) -> Dict[str, Any]:
    return advance_window(api, window, "CANCELLED", cancelled_reason=cancelled_reason)


# ==========================================================================
# Tier 2 — orders
# ==========================================================================
def place_order(
    api: ApiClient,
    menu_item_id: str,
    production_window_id: str,
    delivery_zone_id: str,
    quantity: int = 1,
    diner_headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    headers = DINER_ONE_HEADERS if diner_headers is None else diner_headers
    payload = order_payload(
        menu_item_id, production_window_id, delivery_zone_id, quantity=quantity, **kwargs
    )
    return get_success_data(api.create_order(payload, headers), 201)


def route_order(api: ApiClient, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Routing is the platform's or the finance operator's move."""
    return get_success_data(api.route_order(order_id, ADMIN_HEADERS if headers is None else headers))


_ORDER_ACTOR = {"IN_PRODUCTION": "cook", "HANDED_OFF": "cook", "DELIVERED": "diner"}


def advance_order(
    api: ApiClient,
    order: Dict[str, Any],
    to_status: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if headers is None:
        actor = _ORDER_ACTOR.get(to_status, "cook")
        headers = (
            make_diner_headers(order["diner_user_id"])
            if actor == "diner"
            else make_cook_headers(order["cook_id"])
        )
    return get_success_data(api.advance_order(order["id"], order_advance_payload(to_status), headers))


def cancel_order(
    api: ApiClient,
    order: Dict[str, Any],
    reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    from .factories import order_cancel_payload

    if headers is None:
        headers = make_diner_headers(order["diner_user_id"])
    return get_success_data(api.cancel_order(order["id"], headers, order_cancel_payload(reason)))


def consolidate_hub(api: ApiClient, hub_id: str, production_window_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.consolidate_pickup_hub(hub_id, consolidate_payload(production_window_id), ADMIN_HEADERS)
    )


# ==========================================================================
# Tier 2 — safety incidents
# ==========================================================================
def report_incident(api: ApiClient, cook_id: str, reporter_headers: Optional[Dict[str, str]] = None, **kwargs: Any) -> Dict[str, Any]:
    headers = DINER_ONE_HEADERS if reporter_headers is None else reporter_headers
    return get_success_data(
        api.create_safety_incident(safety_incident_payload(cook_id, **kwargs), headers), 201
    )


def triage_incident(
    api: ApiClient,
    incident_id: str,
    decision: str = "ACCEPT",
    severity_override: Optional[str] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = OFFICER_ONE_HEADERS if officer_headers is None else officer_headers
    return get_success_data(
        api.triage_safety_incident(incident_id, triage_payload(decision, severity_override), headers)
    )


def adjudicate_incident(
    api: ApiClient,
    incident_id: str,
    decision: str = "SUBSTANTIATE",
    resolution_note: Optional[str] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adjudicated by a second officer: the officer who triaged may not adjudicate."""
    headers = OFFICER_TWO_HEADERS if officer_headers is None else officer_headers
    return get_success_data(
        api.adjudicate_safety_incident(
            incident_id, adjudicate_payload(decision, resolution_note), headers
        )
    )


def open_incident(api: ApiClient, cook_id: str, **kwargs: Any) -> Dict[str, Any]:
    """An incident sitting in TRIAGED — the state that blocks payout finalisation."""
    incident = report_incident(api, cook_id, **kwargs)
    return triage_incident(api, incident["id"], "ACCEPT")


def substantiated_incident(api: ApiClient, cook_id: str, **kwargs: Any) -> Dict[str, Any]:
    incident = report_incident(api, cook_id, **kwargs)
    triage_incident(api, incident["id"], "ACCEPT")
    return adjudicate_incident(api, incident["id"], "SUBSTANTIATE")


# ==========================================================================
# Tier 2 — payout statements and refunds
# ==========================================================================
def draft_payout_statement(
    api: ApiClient,
    cook_id: str,
    production_window_id: str,
    basis: str = "ACCRUAL_WINDOW",
    expected_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draft a statement, re-reading the window so the stale-version guard is satisfied."""
    version = (
        window_version(api, production_window_id) if expected_version is None else expected_version
    )
    payload = payout_statement_payload(cook_id, production_window_id, version, basis=basis)
    return get_success_data(
        api.create_payout_statement(payload, FINANCE_ONE_HEADERS if headers is None else headers), 201
    )


def advance_statement(
    api: ApiClient,
    statement_id: str,
    to_status: str,
    note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_payout_statement(
            statement_id,
            statement_advance_payload(to_status, note),
            FINANCE_ONE_HEADERS if headers is None else headers,
        )
    )


def record_refund(api: ApiClient, order_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_refund_event(refund_event_payload(order_id, **kwargs), FINANCE_ONE_HEADERS), 201
    )


# ==========================================================================
# Tier 3 — end-to-end scenarios
# ==========================================================================
def selling_cook(
    api: ApiClient,
    state_code: str = "CA",
    policy_overrides: Optional[Dict[str, Any]] = None,
    cook_overrides: Optional[Dict[str, Any]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    window_overrides: Optional[Dict[str, Any]] = None,
    zone_overrides: Optional[Dict[str, Any]] = None,
    inspection_decision: str = "PASS",
) -> Bag:
    """An ACTIVE cook with one APPROVED dish, one OPEN window and one delivery zone.

    This is the minimum state in which a diner can place an order.
    """
    setup = onboard_active_cook(
        api,
        state_code=state_code,
        policy_overrides=policy_overrides,
        cook_overrides=cook_overrides,
        inspection_decision=inspection_decision,
    )
    item = approved_menu_item(api, setup.cook, **(item_overrides or {}))
    window = open_production_window(api, setup.cook, **(window_overrides or {}))
    zone = create_delivery_zone(
        api, setup.policy["id"], state_code=state_code, **(zone_overrides or {})
    )
    setup.update(menu_item=item, window=window, zone=zone)
    return setup


def add_approved_item(api: ApiClient, setup: Bag, **kwargs: Any) -> Dict[str, Any]:
    """A second approved dish for the same cook."""
    return approved_menu_item(api, setup.cook, **kwargs)


def order_in_scenario(
    api: ApiClient,
    setup: Bag,
    quantity: int = 1,
    diner_headers: Optional[Dict[str, str]] = None,
    menu_item_id: Optional[str] = None,
    zone_id: Optional[str] = None,
) -> Dict[str, Any]:
    return place_order(
        api,
        setup.menu_item["id"] if menu_item_id is None else menu_item_id,
        setup.window["id"],
        setup.zone["id"] if zone_id is None else zone_id,
        quantity=quantity,
        diner_headers=diner_headers,
    )


def routed_order(api: ApiClient, setup: Bag, quantity: int = 1, **kwargs: Any) -> Dict[str, Any]:
    order = order_in_scenario(api, setup, quantity=quantity, **kwargs)
    return route_order(api, order["id"])


def open_window_into_production(api: ApiClient, setup: Bag) -> Dict[str, Any]:
    """Move the clock past the cutoff and walk the window OPEN -> CUTOFF_PASSED -> IN_PRODUCTION."""
    window = read_window(api, setup.window["id"])
    set_clock(api, window["order_cutoff_at"])
    window = advance_window(api, window, "CUTOFF_PASSED")
    window = advance_window(api, window, "IN_PRODUCTION")
    setup["window"] = window
    return window


def hand_off_order(api: ApiClient, setup: Bag, order: Dict[str, Any]) -> Dict[str, Any]:
    """Walk one routed order to HANDED_OFF, moving the clock to the handoff opening."""
    order = advance_order(api, order, "IN_PRODUCTION")
    set_clock(api, setup.window["handoff_start_at"])
    return advance_order(api, order, "HANDED_OFF")


def deliver_order(api: ApiClient, order: Dict[str, Any]) -> Dict[str, Any]:
    """The diner's delivery confirmation — the step that captures a still-authorised payment."""
    return advance_order(api, order, "DELIVERED")


def close_window(api: ApiClient, setup: Bag, at: Optional[str] = None) -> Dict[str, Any]:
    """Move the clock to the end of the handoff interval and close the window."""
    window = read_window(api, setup.window["id"])
    set_clock(api, window["handoff_end_at"] if at is None else at)
    window = advance_window(api, window, "CLOSED")
    setup["window"] = window
    return window


def handed_off_order_scenario(
    api: ApiClient,
    quantity: int = 2,
    state_code: str = "CA",
    policy_overrides: Optional[Dict[str, Any]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    window_overrides: Optional[Dict[str, Any]] = None,
) -> Bag:
    """One order sitting in HANDED_OFF / AUTHORIZED on an IN_PRODUCTION window."""
    setup = selling_cook(
        api,
        state_code=state_code,
        policy_overrides=policy_overrides,
        item_overrides=item_overrides,
        window_overrides=window_overrides,
    )
    order = routed_order(api, setup, quantity=quantity)
    open_window_into_production(api, setup)
    order = hand_off_order(api, setup, order)
    setup["order"] = order
    return setup


def closed_window_scenario(api: ApiClient, **kwargs: Any) -> Bag:
    """A CLOSED window whose handed-off order has been captured by the close cascade."""
    setup = handed_off_order_scenario(api, **kwargs)
    close_window(api, setup)
    setup["order"] = read_order(api, setup.order["id"])
    setup["cook"] = read_cook(api, setup.cook_id)
    return setup
