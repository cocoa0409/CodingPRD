"""The daily opening checkpoint — a single ordered pass (PRD 3.1)."""
from db import store, touch, clock_date, clock_now

from services import derive
from services import cascade


def run_daily_open(course):
    course_id = course["id"]
    today = clock_date()
    now = clock_now()

    # Snapshot belay readiness so that step six can tell "stopped being ready"
    # from "was never ready".
    was_ready = {}
    for element in derive.elements_of_course(course_id):
        if element["status"] != "RETIRED":
            was_ready[element["id"]] = derive.belay_ready(element)

    # Step one — the index and the date.
    course["daily_open_index"] = course["daily_open_index"] + 1
    course["last_daily_open_date"] = today

    # Step two — clear an expired lightning hold before posture is re-derived.
    hold = course["lightning_hold_until"]
    if hold is not None and hold <= now:
        course["lightning_hold_until"] = None

    # Step three — certification currency sweep, ascending created_at.
    for facilitator in derive.facilitators_of_course(course_id):
        derive.refresh_cert_status(facilitator)

    # Step four — element retirement forecast sweep, ascending created_at.
    element_forecast_fields = (
        "calendar_life_forecast_date", "usage_life_forecast_date",
        "retirement_forecast_date", "retirement_basis",
    )
    for element in derive.elements_of_course(course_id):
        if element["status"] == "RETIRED":
            continue
        before = tuple(element[f] for f in element_forecast_fields)
        derive.recompute_element_forecast(element)
        if tuple(element[f] for f in element_forecast_fields) != before:
            touch(element)
        if element["retirement_forecast_date"] <= today and element["status"] != "OUT_OF_SERVICE":
            cascade.element_to_out_of_service(element)

    # Step five — equipment retirement sweep, ascending created_at.
    equipment_forecast_fields = (
        "mfg_life_forecast_date", "service_life_forecast_date",
        "retirement_forecast_date", "retirement_basis",
    )
    for item in derive.equipment_of_course(course_id):
        if item["status"] == "RETIRED":
            continue
        before = tuple(item[f] for f in equipment_forecast_fields)
        derive.recompute_equipment_forecast(item)
        changed = tuple(item[f] for f in equipment_forecast_fields) != before
        if item["retirement_forecast_date"] <= today:
            item["status"] = "RETIRED"
            item["retirement_basis"] = derive.equipment_date_basis(item)
            changed = True
        if changed:
            touch(item)

    # Step six — belay readiness re-derived; blocks that lost readiness block out.
    for element in derive.elements_of_course(course_id):
        if element["status"] == "RETIRED":
            continue
        cascade.propagate_belay_loss(element, was_ready.get(element["id"], False))

    # Step seven — posture from the results of steps two through six.
    derive.recompute_posture(course, bump_version=False)

    # Step eight — release weather holds when the posture settled at OPEN.
    if course["posture"] == "OPEN":
        cascade.release_weather_holds(course)

    # Step nine — the course's version increments.
    touch(course)
