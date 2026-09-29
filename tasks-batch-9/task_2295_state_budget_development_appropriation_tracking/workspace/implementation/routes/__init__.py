"""Blueprint registry."""

from routes import agencies
from routes import agency_requests
from routes import allotments
from routes import appropriations
from routes import budget_cycles
from routes import budget_transfers
from routes import clock_routes
from routes import committee_actions
from routes import decision_packages
from routes import executive_recommendations
from routes import expenditures
from routes import federal_grants
from routes import reduction_scenarios
from routes import revenue_forecasts

BLUEPRINTS = (
    agencies.bp,
    budget_cycles.bp,
    revenue_forecasts.bp,
    agency_requests.bp,
    decision_packages.bp,
    executive_recommendations.bp,
    reduction_scenarios.bp,
    appropriations.bp,
    committee_actions.bp,
    allotments.bp,
    budget_transfers.bp,
    expenditures.bp,
    federal_grants.bp,
    clock_routes.bp,
)
