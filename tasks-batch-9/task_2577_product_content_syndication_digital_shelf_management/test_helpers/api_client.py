"""API client: one method per endpoint of the Product Content Syndication &
Digital Shelf API (PRD §4).  Everything is mounted under /digital-shelf."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/digital-shelf"


class ApiClient(GenericApiClient):
    # ---------------- retailers ----------------
    def create_retailer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retailers", payload, headers)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"{PREFIX}/retailers/{retailer_id}", headers=headers)

    def list_retailers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/retailers", headers=headers, params=params)

    def patch_retailer(self, retailer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/retailers/{retailer_id}", payload, headers)

    def create_retailer_requirement(self, retailer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retailers/{retailer_id}/requirements", payload, headers
        )

    def list_retailer_requirements(self, retailer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/retailers/{retailer_id}/requirements", headers=headers, params=params
        )

    # ---------------- attribute taxonomy ----------------
    def create_attribute_definition(self, payload, headers):
        return self._request("POST", f"{PREFIX}/attribute-definitions", payload, headers)

    def list_attribute_definitions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/attribute-definitions", headers=headers, params=params
        )

    # ---------------- products ----------------
    def create_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    def get_shelf_summary(self, product_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/products/{product_id}/shelf-summary", headers=headers, params=params
        )

    # ---------------- content revisions ----------------
    def create_content_version(self, payload, headers):
        return self._request("POST", f"{PREFIX}/content-versions", payload, headers)

    def get_content_version(self, content_version_id, headers):
        return self._request(
            "GET", f"{PREFIX}/content-versions/{content_version_id}", headers=headers
        )

    def list_content_versions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/content-versions", headers=headers, params=params)

    def create_attribute_value(self, content_version_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/content-versions/{content_version_id}/attribute-values",
            payload,
            headers,
        )

    def list_attribute_values(self, content_version_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/content-versions/{content_version_id}/attribute-values",
            headers=headers,
            params=params,
        )

    # ---------------- media assets ----------------
    def create_media_asset(self, payload, headers):
        return self._request("POST", f"{PREFIX}/media-assets", payload, headers)

    def get_media_asset(self, media_asset_id, headers):
        return self._request("GET", f"{PREFIX}/media-assets/{media_asset_id}", headers=headers)

    def list_media_assets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/media-assets", headers=headers, params=params)

    def decide_media_asset(self, media_asset_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/media-assets/{media_asset_id}/retailer-decision", payload, headers
        )

    # ---------------- retailer listings ----------------
    def create_retailer_listing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retailer-listings", payload, headers)

    def get_retailer_listing(self, listing_id, headers):
        return self._request("GET", f"{PREFIX}/retailer-listings/{listing_id}", headers=headers)

    def list_retailer_listings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/retailer-listings", headers=headers, params=params)

    def get_listing_completeness(self, listing_id, headers):
        return self._request(
            "GET", f"{PREFIX}/retailer-listings/{listing_id}/completeness", headers=headers
        )

    def create_observation(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retailer-listings/{listing_id}/observations", payload, headers
        )

    def list_observations(self, listing_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/retailer-listings/{listing_id}/observations",
            headers=headers,
            params=params,
        )

    def set_shelf_status(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retailer-listings/{listing_id}/shelf-status", payload, headers
        )

    # ---------------- change requests ----------------
    def create_change_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/change-requests", payload, headers)

    def get_change_request(self, change_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/change-requests/{change_request_id}", headers=headers
        )

    def list_change_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/change-requests", headers=headers, params=params)

    def submit_change_request(self, change_request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/change-requests/{change_request_id}/submit", payload, headers
        )

    def create_review(self, change_request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/change-requests/{change_request_id}/reviews", payload, headers
        )

    # ---------------- syndication jobs ----------------
    def create_syndication_job(self, payload, headers):
        return self._request("POST", f"{PREFIX}/syndication-jobs", payload, headers)

    def get_syndication_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/syndication-jobs/{job_id}", headers=headers)

    def list_syndication_jobs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/syndication-jobs", headers=headers, params=params)

    def transmit_syndication_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/syndication-jobs/{job_id}/transmit", payload, headers
        )

    def retailer_response(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/syndication-jobs/{job_id}/retailer-response", payload, headers
        )

    def list_rejection_errors(self, job_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/syndication-jobs/{job_id}/rejection-errors",
            headers=headers,
            params=params,
        )

    def resolve_rejection_error(self, rejection_error_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rejection-errors/{rejection_error_id}/resolve", payload, headers
        )

    def requeue_syndication_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/syndication-jobs/{job_id}/requeue", payload, headers
        )

    def cancel_syndication_job(self, job_id, payload, headers):
        return self._request("POST", f"{PREFIX}/syndication-jobs/{job_id}/cancel", payload, headers)

    # ---------------- enhanced content deployments ----------------
    def create_enhanced_deployment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/enhanced-deployments", payload, headers)

    def get_enhanced_deployment(self, deployment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/enhanced-deployments/{deployment_id}", headers=headers
        )

    def list_enhanced_deployments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/enhanced-deployments", headers=headers, params=params
        )

    def decide_enhanced_deployment(self, deployment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/enhanced-deployments/{deployment_id}/retailer-decision",
            payload,
            headers,
        )

    def withdraw_enhanced_deployment(self, deployment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/enhanced-deployments/{deployment_id}/withdraw", payload, headers
        )

    # ---------------- shelf alerts ----------------
    def get_shelf_alert(self, alert_id, headers):
        return self._request("GET", f"{PREFIX}/shelf-alerts/{alert_id}", headers=headers)

    def list_shelf_alerts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shelf-alerts", headers=headers, params=params)

    def acknowledge_shelf_alert(self, alert_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shelf-alerts/{alert_id}/acknowledge", payload, headers
        )

    def resolve_shelf_alert(self, alert_id, payload, headers):
        return self._request("POST", f"{PREFIX}/shelf-alerts/{alert_id}/resolve", payload, headers)

    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
