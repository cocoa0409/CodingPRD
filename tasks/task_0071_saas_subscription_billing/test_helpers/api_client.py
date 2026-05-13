"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Tenants (PRD §3.2, §4)
    # =======================================================================
    def create_tenant(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/tenants", payload, headers)

    def list_tenants(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/tenants", headers=headers, params=params,
        )

    def get_tenant(self, tenant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tenants/{tenant_id}", headers=headers,
        )

    def update_tenant(self, tenant_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/tenants/{tenant_id}", payload, headers,
        )

    def delete_tenant(self, tenant_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/tenants/{tenant_id}", headers=headers,
        )

    # =======================================================================
    # Packages (PRD §3.1, §4)
    # =======================================================================
    def create_package(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/packages", payload, headers)

    def list_packages(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/packages", headers=headers, params=params,
        )

    def get_package(self, package_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/packages/{package_id}", headers=headers,
        )

    # =======================================================================
    # Subscriptions (PRD §3.3, §3.4, §4)
    # =======================================================================
    def create_subscription(self, tenant_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/tenants/{tenant_id}/subscriptions",
            payload, headers,
        )

    def get_subscription(self, tenant_id: str, subscription_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}",
            headers=headers,
        )

    def convert_subscription(self, tenant_id: str, subscription_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}/convert",
            payload or {}, headers,
        )

    def upgrade_subscription(self, tenant_id: str, subscription_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}/upgrade",
            payload, headers,
        )

    def downgrade_subscription(self, tenant_id: str, subscription_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}/downgrade",
            payload, headers,
        )

    def cancel_subscription(self, tenant_id: str, subscription_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "DELETE",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}",
            headers=headers, params=params,
        )

    def list_subscription_changes(self, tenant_id: str,
                                  subscription_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}/changes",
            headers=headers, params=params,
        )

    # =======================================================================
    # Usage (PRD §3.7, §4)
    # =======================================================================
    def ingest_usage(self, tenant_id: str, subscription_id: str,
                     payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}/usage",
            payload, headers,
        )

    def list_usage(self, tenant_id: str, subscription_id: str,
                   headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/tenants/{tenant_id}/subscriptions/{subscription_id}/usage",
            headers=headers, params=params,
        )

    # =======================================================================
    # Invoices (PRD §3.9, §4)
    # =======================================================================
    def list_invoices(self, tenant_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tenants/{tenant_id}/invoices",
            headers=headers, params=params,
        )

    def get_invoice(self, tenant_id: str, invoice_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/tenants/{tenant_id}/invoices/{invoice_id}",
            headers=headers,
        )

    def update_invoice(self, tenant_id: str, invoice_id: str,
                       payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/tenants/{tenant_id}/invoices/{invoice_id}",
            payload, headers,
        )

    def issue_invoice(self, tenant_id: str, invoice_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/tenants/{tenant_id}/invoices/{invoice_id}/issue",
            payload or {}, headers,
        )

    def create_payment(self, tenant_id: str, invoice_id: str,
                       payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/tenants/{tenant_id}/invoices/{invoice_id}/payments",
            payload, headers,
        )

    # =======================================================================
    # Credit notes (PRD §3.11, §4)
    # =======================================================================
    def create_credit_note(self, tenant_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/tenants/{tenant_id}/credit-notes",
            payload, headers,
        )

    def list_credit_notes(self, tenant_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tenants/{tenant_id}/credit-notes",
            headers=headers, params=params,
        )

    # =======================================================================
    # Jurisdictions (PRD §3.13, §4)
    # =======================================================================
    def create_jurisdiction(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/jurisdictions", headers=headers, params=params,
        )

    # =======================================================================
    # Sync events & audit (PRD §2.13, §4)
    # =======================================================================
    def list_sync_events(self, tenant_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tenants/{tenant_id}/sync-events",
            headers=headers, params=params,
        )

    def list_audit_logs(self, tenant_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/tenants/{tenant_id}/audit-logs",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test-harness drivers (PRD §3.14, §4)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def dunning_run(self, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_dunning/run", payload or {}, headers,
        )

    def archive_run(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/_archive/run", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
