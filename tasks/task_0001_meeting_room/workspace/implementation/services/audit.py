import db


def create_audit_log(actor_id, actor_role, action, resource_type, resource_id, details=None):
    log_id = db.gen_id()
    entry = {
        "id": log_id,
        "timestamp": db.now_iso(),
        "actor_id": actor_id,
        "actor_role": actor_role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details or {},
    }
    db.audit_logs[log_id] = entry
    return entry
