import uuid
from clock import logical_clock


def new_id():
    return str(uuid.uuid4())


def now_ts():
    return logical_clock.now()


def format_ts(dt):
    return logical_clock.format_timestamp(dt)


class VersionedModel:
    def __init__(self):
        self.id = new_id()
        ts = now_ts()
        self.created_at = ts
        self.updated_at = ts
        self.version = 1

    def touch(self):
        self.updated_at = now_ts()
        self.version += 1

    def check_version(self, client_version):
        from errors import raise_error, ERR_VERSION_CONFLICT
        if client_version is not None and client_version != self.version:
            raise_error(ERR_VERSION_CONFLICT, "Version conflict.")

    def base_dict(self):
        return {
            "id": self.id,
            "created_at": format_ts(self.created_at),
            "updated_at": format_ts(self.updated_at),
            "version": self.version,
        }


class SimpleModel:
    def __init__(self):
        self.id = new_id()
        self.created_at = now_ts()

    def base_dict(self):
        return {
            "id": self.id,
            "created_at": format_ts(self.created_at),
        }
