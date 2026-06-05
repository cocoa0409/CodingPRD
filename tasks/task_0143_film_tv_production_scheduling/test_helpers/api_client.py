"""API client: one method per endpoint defined in the PRD.

Flat top-level collections; parent ids travel in the request body, not the path.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Production -------------------------------------------------------- #
    def create_production(self, payload, headers):
        return self._request("POST", "/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/productions/{production_id}", headers=headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/productions", headers=headers, params=params)

    def advance_production(self, production_id, headers):
        return self._request("POST", f"/productions/{production_id}/advance", {}, headers)

    def close_production(self, production_id, headers):
        return self._request("POST", f"/productions/{production_id}/close", {}, headers)

    def get_budget_summary(self, production_id, headers):
        return self._request("GET", f"/productions/{production_id}/budget-summary", headers=headers)

    # ---- BudgetLine -------------------------------------------------------- #
    def create_budget_line(self, payload, headers):
        return self._request("POST", "/budget-lines", payload, headers)

    def get_budget_line(self, budget_line_id, headers):
        return self._request("GET", f"/budget-lines/{budget_line_id}", headers=headers)

    def list_budget_lines(self, headers, params=None):
        return self._request("GET", "/budget-lines", headers=headers, params=params)

    def post_actual(self, budget_line_id, payload, headers):
        return self._request("POST", f"/budget-lines/{budget_line_id}/post-actual", payload, headers)

    # ---- ShootingDay ------------------------------------------------------- #
    def create_shooting_day(self, payload, headers):
        return self._request("POST", "/shooting-days", payload, headers)

    def get_shooting_day(self, shooting_day_id, headers):
        return self._request("GET", f"/shooting-days/{shooting_day_id}", headers=headers)

    def list_shooting_days(self, headers, params=None):
        return self._request("GET", "/shooting-days", headers=headers, params=params)

    def start_shooting_day(self, shooting_day_id, headers):
        return self._request("POST", f"/shooting-days/{shooting_day_id}/start", {}, headers)

    def wrap_shooting_day(self, shooting_day_id, headers):
        return self._request("POST", f"/shooting-days/{shooting_day_id}/wrap", {}, headers)

    def cancel_shooting_day(self, shooting_day_id, headers):
        return self._request("POST", f"/shooting-days/{shooting_day_id}/cancel", {}, headers)

    # ---- Scene ------------------------------------------------------------- #
    def create_scene(self, payload, headers):
        return self._request("POST", "/scenes", payload, headers)

    def get_scene(self, scene_id, headers):
        return self._request("GET", f"/scenes/{scene_id}", headers=headers)

    def list_scenes(self, headers, params=None):
        return self._request("GET", "/scenes", headers=headers, params=params)

    def schedule_scene(self, scene_id, payload, headers):
        return self._request("POST", f"/scenes/{scene_id}/schedule", payload, headers)

    # ---- CrewMember -------------------------------------------------------- #
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/crew-members", headers=headers, params=params)

    # ---- Assignment -------------------------------------------------------- #
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-in", {}, headers)

    def check_out_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-out", payload, headers)

    def no_show_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/no-show", {}, headers)

    def approve_pay_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/approve-pay", {}, headers)

    def mark_paid_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/mark-paid", {}, headers)

    # ---- CallSheet --------------------------------------------------------- #
    def create_call_sheet(self, payload, headers):
        return self._request("POST", "/call-sheets", payload, headers)

    def get_call_sheet(self, call_sheet_id, headers):
        return self._request("GET", f"/call-sheets/{call_sheet_id}", headers=headers)

    def list_call_sheets(self, headers, params=None):
        return self._request("GET", "/call-sheets", headers=headers, params=params)

    def publish_call_sheet(self, call_sheet_id, headers):
        return self._request("POST", f"/call-sheets/{call_sheet_id}/publish", {}, headers)

    def revise_call_sheet(self, call_sheet_id, headers, payload=None):
        return self._request("POST", f"/call-sheets/{call_sheet_id}/revise", payload or {}, headers)

    def finalize_call_sheet(self, call_sheet_id, headers):
        return self._request("POST", f"/call-sheets/{call_sheet_id}/finalize", {}, headers)

    # ---- Location & LocationPermit ---------------------------------------- #
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def create_location_permit(self, payload, headers):
        return self._request("POST", "/location-permits", payload, headers)

    def get_location_permit(self, permit_id, headers):
        return self._request("GET", f"/location-permits/{permit_id}", headers=headers)

    def list_location_permits(self, headers, params=None):
        return self._request("GET", "/location-permits", headers=headers, params=params)

    def approve_location_permit(self, permit_id, headers):
        return self._request("POST", f"/location-permits/{permit_id}/approve", {}, headers)

    def deny_location_permit(self, permit_id, headers):
        return self._request("POST", f"/location-permits/{permit_id}/deny", {}, headers)

    def activate_location_permit(self, permit_id, headers):
        return self._request("POST", f"/location-permits/{permit_id}/activate", {}, headers)

    def expire_location_permit(self, permit_id, headers):
        return self._request("POST", f"/location-permits/{permit_id}/expire", {}, headers)

    def revoke_location_permit(self, permit_id, headers):
        return self._request("POST", f"/location-permits/{permit_id}/revoke", {}, headers)

    # ---- ResidualEvent ----------------------------------------------------- #
    def create_residual_event(self, payload, headers):
        return self._request("POST", "/residual-events", payload, headers)

    def get_residual_event(self, residual_event_id, headers):
        return self._request("GET", f"/residual-events/{residual_event_id}", headers=headers)

    def list_residual_events(self, headers, params=None):
        return self._request("GET", "/residual-events", headers=headers, params=params)

    # ---- UnionFringe ------------------------------------------------------- #
    def create_union_fringe(self, payload, headers):
        return self._request("POST", "/union-fringes", payload, headers)

    def get_union_fringe(self, union_fringe_id, headers):
        return self._request("GET", f"/union-fringes/{union_fringe_id}", headers=headers)

    def list_union_fringes(self, headers, params=None):
        return self._request("GET", "/union-fringes", headers=headers, params=params)

    # ---- Dailies ----------------------------------------------------------- #
    def create_dailies(self, payload, headers):
        return self._request("POST", "/dailies", payload, headers)

    def get_dailies(self, dailies_id, headers):
        return self._request("GET", f"/dailies/{dailies_id}", headers=headers)

    def list_dailies(self, headers, params=None):
        return self._request("GET", "/dailies", headers=headers, params=params)

    def start_review_dailies(self, dailies_id, headers):
        return self._request("POST", f"/dailies/{dailies_id}/start-review", {}, headers)

    def approve_dailies(self, dailies_id, headers):
        return self._request("POST", f"/dailies/{dailies_id}/approve", {}, headers)

    def flag_dailies(self, dailies_id, payload, headers):
        return self._request("POST", f"/dailies/{dailies_id}/flag", payload, headers)

    def archive_dailies(self, dailies_id, headers):
        return self._request("POST", f"/dailies/{dailies_id}/archive", {}, headers)


api_client = ApiClient()
