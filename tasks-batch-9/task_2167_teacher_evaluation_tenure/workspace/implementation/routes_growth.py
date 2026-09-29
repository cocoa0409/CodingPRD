"""Student growth measures."""
import services as svc
from auth import authenticate
from errors import err
from response import created, ok, paginated, pagination
from store import S, new_record, touch
from validation import body, query_enum, v_enum, v_int, v_num, v_str

ALL_ROLES = ("HrAdmin", "Evaluator", "Teacher", "AppealPanelist", "UnionRep")
MEASURE_CODES = ("STATE_ASSESSMENT", "SLO", "SCHOOLWIDE")
MEASURE_STATUSES = ("REPORTED", "CERTIFIED", "EXCLUDED")


def register(app):
    @app.post("/growth-measures")
    def create_growth_measure():
        authenticate(("HrAdmin",))
        data = body()
        cycle_id = v_str(data, "cycle_id")
        measure_code = v_enum(data, "measure_code", MEASURE_CODES)
        index_value = v_num(data, "index_value", minimum=1.00, maximum=4.00)
        coverage_pct = v_num(data, "coverage_pct", exclusive_min=0, maximum=100)
        expected = v_int(data, "expected_cycle_version")
        cycle = S.cycles.get(cycle_id)
        if cycle is None:
            raise err("ERR_CYCLE_NOT_FOUND")
        if expected != cycle["version"]:
            raise err("ERR_STALE_CYCLE_VERSION")
        for measure in svc.growth_measures_of_cycle(cycle_id):
            if measure["measure_code"] == measure_code and measure["status"] in ("REPORTED", "CERTIFIED"):
                measure["status"] = "EXCLUDED"
                touch(measure)
        record = new_record(
            cycle_id=cycle_id,
            measure_code=measure_code,
            index_value=index_value,
            coverage_pct=coverage_pct,
            status="REPORTED",
            cycle_version_after=None,
        )
        S.growth_measures[record["id"]] = record
        svc.recompute_growth_component(cycle)
        touch(cycle)
        record["cycle_version_after"] = cycle["version"]
        return created(svc.ser_growth_measure(record))

    @app.get("/evaluation-cycles/<cycle_id>/growth-measures")
    def list_growth_measures(cycle_id):
        authenticate(ALL_ROLES)
        status = query_enum("status", MEASURE_STATUSES)
        measure_code = query_enum("measure_code", MEASURE_CODES)
        pagination()
        if cycle_id not in S.cycles:
            raise err("ERR_CYCLE_NOT_FOUND")
        items = svc.growth_measures_of_cycle(cycle_id)
        if status is not None:
            items = [i for i in items if i["status"] == status]
        if measure_code is not None:
            items = [i for i in items if i["measure_code"] == measure_code]
        return paginated(items, svc.ser_growth_measure)

    @app.post("/growth-measures/<measure_id>/certify")
    def certify_growth_measure(measure_id):
        authenticate(("HrAdmin",))
        measure = S.growth_measures.get(measure_id)
        if measure is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        if measure["status"] != "REPORTED":
            raise err("ERR_INVALID_REQUEST", "Only a REPORTED growth measure may be certified.")
        cycle = S.cycles.get(measure["cycle_id"])
        if cycle is None or cycle["status"] not in ("SCHEDULING", "SCORING"):
            raise err("ERR_CYCLE_STATE_INVALID")
        measure["status"] = "CERTIFIED"
        touch(measure)
        svc.recompute_growth_component(cycle)
        touch(cycle)
        return ok(svc.ser_growth_measure(measure))
