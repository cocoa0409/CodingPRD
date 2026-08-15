"""Error classes and catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    return ApiError(error_id, message, http_status)


# Convenience constructors -------------------------------------------------

def validation(msg="Request validation failed"):
    return err("ERR_VALIDATION", msg, 400)


def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return err("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return err("ERR_FORBIDDEN", msg, 403)


def sod(msg="Segregation of duties violation"):
    return err("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def stale_version(msg="expected_show_event_version does not match the show's current version"):
    return err("ERR_STALE_VERSION", msg, 412)


def not_found(error_id, msg):
    return err(error_id, msg, 404)


def conflict(error_id, msg):
    return err(error_id, msg, 409)
