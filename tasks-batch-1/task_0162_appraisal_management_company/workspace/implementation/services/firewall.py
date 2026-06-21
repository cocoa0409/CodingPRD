"""AIR independence firewall (PRD §2.4, validation priority 2)."""
import db
import errors


def block_and_log(order_id, actor_role, blocked_operation):
    """Record a FirewallEvent and raise ERR_AIR_FIREWALL_VIOLATION."""
    event = {
        "order_id": order_id,
        "actor_role": actor_role,
        "blocked_operation": blocked_operation,
        "error_id": errors.ERR_AIR_FIREWALL_VIOLATION,
    }
    # FirewallEvent is audit-only: id + created_at only (no updated_at/version).
    db.stamp_create(event, mutable=False)
    db.firewall_events[event["id"]] = event
    raise errors.firewall(
        "Loan-production side is firewalled from %s." % blocked_operation)
