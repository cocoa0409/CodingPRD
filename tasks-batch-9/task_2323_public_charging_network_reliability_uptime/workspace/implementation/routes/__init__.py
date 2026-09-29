"""Blueprint registry."""
from routes.clock_route import bp as clock_bp
from routes.host_sites import bp as host_sites_bp
from routes.stations import bp as stations_bp
from routes.charging_ports import bp as charging_ports_bp
from routes.outage_events import bp as outage_events_bp
from routes.dispatches import bp as dispatches_bp
from routes.spare_parts import bp as spare_parts_bp
from routes.part_reservations import bp as part_reservations_bp
from routes.uptime_reports import bp as uptime_reports_bp
from routes.claims import bp as claims_bp
from routes.complaints import bp as complaints_bp

ALL_BLUEPRINTS = (
    clock_bp,
    host_sites_bp,
    stations_bp,
    charging_ports_bp,
    outage_events_bp,
    dispatches_bp,
    spare_parts_bp,
    part_reservations_bp,
    uptime_reports_bp,
    claims_bp,
    complaints_bp,
)
