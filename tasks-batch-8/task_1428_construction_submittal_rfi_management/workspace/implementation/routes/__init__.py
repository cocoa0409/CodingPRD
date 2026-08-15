from routes.projects import bp as projects_bp
from routes.spec_sections import bp as spec_sections_bp
from routes.subcontractors import bp as subcontractors_bp
from routes.reviewers import bp as reviewers_bp
from routes.submittals import bp as submittals_bp
from routes.revisions import bp as revisions_bp
from routes.long_lead_items import bp as lli_bp
from routes.rfis import bp as rfis_bp
from routes.impact_assessments import bp as assessments_bp
from routes.distribution_records import bp as distributions_bp
from routes.installation_activities import bp as activities_bp
from routes.owner_reports import bp as reports_bp
from routes.escalation_events import bp as events_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = [
    projects_bp, spec_sections_bp, subcontractors_bp, reviewers_bp,
    submittals_bp, revisions_bp, lli_bp, rfis_bp, assessments_bp,
    distributions_bp, activities_bp, reports_bp, events_bp, clock_bp,
]
