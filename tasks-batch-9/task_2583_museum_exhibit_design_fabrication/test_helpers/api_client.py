"""One method per endpoint of the exhibit design and fabrication API.

Every method returns the raw response so a test can assert on the status code
as well as the body. Action endpoints that take no body send an empty JSON
object.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the endpoint table."""

    # -- logical clock ----------------------------------------------------
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # -- exhibit projects -------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/exhibit-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/exhibit-projects", None, headers, params)

    def get_project(self, project_id, headers):
        return self._request("GET", "/exhibit-projects/%s" % project_id, None, headers)

    def advance_phase(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/advance-phase" % project_id, payload, headers
        )

    def closeout(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/closeout" % project_id, payload, headers
        )

    def review_sweep(self, project_id, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/review-sweep" % project_id, {}, headers
        )

    # -- design packages --------------------------------------------------
    def create_design_package(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/design-packages" % project_id, payload, headers
        )

    def list_design_packages(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/design-packages" % project_id,
            None,
            headers,
            params,
        )

    def get_design_package(self, package_id, headers):
        return self._request("GET", "/design-packages/%s" % package_id, None, headers)

    def list_superseded_packages(self, package_id, headers, params=None):
        return self._request(
            "GET",
            "/design-packages/%s/superseded-packages" % package_id,
            None,
            headers,
            params,
        )

    # -- review rounds and votes -----------------------------------------
    def create_review_round(self, package_id, payload, headers):
        return self._request(
            "POST", "/design-packages/%s/review-rounds" % package_id, payload, headers
        )

    def list_review_rounds(self, package_id, headers, params=None):
        return self._request(
            "GET",
            "/design-packages/%s/review-rounds" % package_id,
            None,
            headers,
            params,
        )

    def get_review_round(self, round_id, headers):
        return self._request("GET", "/review-rounds/%s" % round_id, None, headers)

    def cast_vote(self, round_id, payload, headers):
        return self._request(
            "POST", "/review-rounds/%s/votes" % round_id, payload, headers
        )

    def list_votes(self, round_id, headers, params=None):
        return self._request(
            "GET", "/review-rounds/%s/votes" % round_id, None, headers, params
        )

    # -- gallery zones ----------------------------------------------------
    def create_gallery_zone(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/gallery-zones" % project_id, payload, headers
        )

    def list_gallery_zones(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/gallery-zones" % project_id,
            None,
            headers,
            params,
        )

    def get_gallery_zone(self, zone_id, headers):
        return self._request("GET", "/gallery-zones/%s" % zone_id, None, headers)

    def list_zone_artifact_cases(self, zone_id, headers, params=None):
        return self._request(
            "GET", "/gallery-zones/%s/artifact-cases" % zone_id, None, headers, params
        )

    def list_zone_install_windows(self, zone_id, headers, params=None):
        return self._request(
            "GET", "/gallery-zones/%s/install-windows" % zone_id, None, headers, params
        )

    # -- artifact cases and placements ------------------------------------
    def create_artifact_case(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/artifact-cases" % project_id, payload, headers
        )

    def list_artifact_cases(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/artifact-cases" % project_id,
            None,
            headers,
            params,
        )

    def get_artifact_case(self, case_id, headers):
        return self._request("GET", "/artifact-cases/%s" % case_id, None, headers)

    def create_placement(self, case_id, payload, headers):
        return self._request(
            "POST", "/artifact-cases/%s/placements" % case_id, payload, headers
        )

    def list_placements(self, case_id, headers, params=None):
        return self._request(
            "GET", "/artifact-cases/%s/placements" % case_id, None, headers, params
        )

    def delete_placement(self, case_id, artifact_id, headers):
        return self._request(
            "DELETE",
            "/artifact-cases/%s/placements/%s" % (case_id, artifact_id),
            None,
            headers,
        )

    def submit_case_for_conservation(self, case_id, headers):
        return self._request(
            "POST", "/artifact-cases/%s/submit-for-conservation" % case_id, {}, headers
        )

    def case_conservator_decision(self, case_id, payload, headers):
        return self._request(
            "POST", "/artifact-cases/%s/conservator-decision" % case_id, payload, headers
        )

    def mount_advance(self, case_id, payload, headers):
        return self._request(
            "POST", "/artifact-cases/%s/mount-advance" % case_id, payload, headers
        )

    # -- collection objects ------------------------------------------------
    def create_artifact(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/artifacts" % project_id, payload, headers
        )

    def list_artifacts(self, project_id, headers, params=None):
        return self._request(
            "GET", "/exhibit-projects/%s/artifacts" % project_id, None, headers, params
        )

    def get_artifact(self, artifact_id, headers):
        return self._request("GET", "/artifacts/%s" % artifact_id, None, headers)

    # -- interactives ------------------------------------------------------
    def create_interactive(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/interactives" % project_id, payload, headers
        )

    def list_interactives(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/interactives" % project_id,
            None,
            headers,
            params,
        )

    def get_interactive(self, interactive_id, headers):
        return self._request("GET", "/interactives/%s" % interactive_id, None, headers)

    def submit_prototype(self, interactive_id, payload, headers):
        return self._request(
            "POST", "/interactives/%s/submit-prototype" % interactive_id, payload, headers
        )

    def prototype_decision(self, interactive_id, payload, headers):
        return self._request(
            "POST",
            "/interactives/%s/prototype-decision" % interactive_id,
            payload,
            headers,
        )

    def mark_fabricated(self, interactive_id, headers):
        return self._request(
            "POST", "/interactives/%s/mark-fabricated" % interactive_id, {}, headers
        )

    def commission_interactive(self, interactive_id, payload, headers):
        return self._request(
            "POST", "/interactives/%s/commission" % interactive_id, payload or {}, headers
        )

    # -- material specifications -------------------------------------------
    def create_material_spec(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/material-specs" % project_id, payload, headers
        )

    def list_material_specs(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/material-specs" % project_id,
            None,
            headers,
            params,
        )

    def get_material_spec(self, material_id, headers):
        return self._request("GET", "/material-specs/%s" % material_id, None, headers)

    def list_material_shop_drawings(self, material_id, headers, params=None):
        return self._request(
            "GET",
            "/material-specs/%s/shop-drawings" % material_id,
            None,
            headers,
            params,
        )

    def submit_material_for_conservation(self, material_id, headers):
        return self._request(
            "POST",
            "/material-specs/%s/submit-for-conservation" % material_id,
            {},
            headers,
        )

    def material_conservator_decision(self, material_id, payload, headers):
        return self._request(
            "POST",
            "/material-specs/%s/conservator-decision" % material_id,
            payload,
            headers,
        )

    # -- shop drawings -----------------------------------------------------
    def create_shop_drawing(self, payload, headers):
        return self._request("POST", "/shop-drawings", payload, headers)

    def list_shop_drawings(self, headers, params=None):
        return self._request("GET", "/shop-drawings", None, headers, params)

    def list_project_shop_drawings(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/shop-drawings" % project_id,
            None,
            headers,
            params,
        )

    def get_shop_drawing(self, drawing_id, headers):
        return self._request("GET", "/shop-drawings/%s" % drawing_id, None, headers)

    def start_drawing_review(self, drawing_id, headers):
        return self._request(
            "POST", "/shop-drawings/%s/start-review" % drawing_id, {}, headers
        )

    def drawing_decision(self, drawing_id, payload, headers):
        return self._request(
            "POST", "/shop-drawings/%s/decision" % drawing_id, payload, headers
        )

    def void_drawing(self, drawing_id, payload, headers):
        return self._request(
            "POST", "/shop-drawings/%s/void" % drawing_id, payload, headers
        )

    # -- install windows ---------------------------------------------------
    def create_install_window(self, payload, headers):
        return self._request("POST", "/install-windows", payload, headers)

    def list_project_install_windows(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/install-windows" % project_id,
            None,
            headers,
            params,
        )

    def get_install_window(self, window_id, headers):
        return self._request("GET", "/install-windows/%s" % window_id, None, headers)

    def window_decision(self, window_id, payload, headers):
        return self._request(
            "POST", "/install-windows/%s/decision" % window_id, payload, headers
        )

    def start_window(self, window_id, headers):
        return self._request(
            "POST", "/install-windows/%s/start" % window_id, {}, headers
        )

    def complete_window(self, window_id, headers):
        return self._request(
            "POST", "/install-windows/%s/complete" % window_id, {}, headers
        )

    def cancel_window(self, window_id, headers, payload=None):
        return self._request(
            "POST", "/install-windows/%s/cancel" % window_id, payload or {}, headers
        )

    # -- punch items -------------------------------------------------------
    def create_punch_item(self, project_id, payload, headers):
        return self._request(
            "POST", "/exhibit-projects/%s/punch-items" % project_id, payload, headers
        )

    def list_project_punch_items(self, project_id, headers, params=None):
        return self._request(
            "GET",
            "/exhibit-projects/%s/punch-items" % project_id,
            None,
            headers,
            params,
        )

    def list_punch_items(self, headers, params=None):
        return self._request("GET", "/punch-items", None, headers, params)

    def get_punch_item(self, item_id, headers):
        return self._request("GET", "/punch-items/%s" % item_id, None, headers)

    def verify_punch_item(self, item_id, payload, headers):
        return self._request(
            "POST", "/punch-items/%s/verify" % item_id, payload, headers
        )

    def waive_punch_item(self, item_id, payload, headers):
        return self._request("POST", "/punch-items/%s/waive" % item_id, payload, headers)
