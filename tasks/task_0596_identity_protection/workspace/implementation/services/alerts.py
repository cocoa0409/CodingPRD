from db import db, new_row


def create_alert(subscriber_id, family_member_id, alert_type, severity, source_detail):
    alert = new_row(
        subscriber_id=subscriber_id,
        family_member_id=family_member_id,
        alert_type=alert_type,
        severity=severity,
        source_detail=source_detail,
        status="NEW",
        escalation_tier=None,
        escalation_deadline=None,
        dismissal_reason=None,
    )
    db.alerts[alert["id"]] = alert
    return alert
