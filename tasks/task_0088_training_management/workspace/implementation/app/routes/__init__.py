"""Route registration."""
from flask import Flask

from . import (
    audit_routes,
    category_routes,
    certificate_routes,
    classroom_routes,
    clock_routes,
    course_routes,
    credit_routes,
    enrollment_routes,
    evaluation_routes,
    exam_routes,
    instructor_routes,
    online_room_routes,
    session_routes,
    sync_routes,
    trainee_routes,
)


def register_all_routes(app: Flask) -> None:
    category_routes.register(app)
    course_routes.register(app)
    instructor_routes.register(app)
    classroom_routes.register(app)
    online_room_routes.register(app)
    session_routes.register(app)
    enrollment_routes.register(app)
    exam_routes.register(app)
    evaluation_routes.register(app)
    credit_routes.register(app)
    certificate_routes.register(app)
    trainee_routes.register(app)
    sync_routes.register(app)
    audit_routes.register(app)
    clock_routes.register(app)
