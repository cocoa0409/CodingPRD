from routes.buildings import bp as buildings_bp
from routes.rooms import bp as rooms_bp
from routes.groups import bp as groups_bp
from routes.participants import bp as participants_bp
from routes.stays import bp as stays_bp
from routes.turns import bp as turns_bp
from routes.screenings import bp as screenings_bp
from routes.linen import bp as linen_bp
from routes.keys import bp as keys_bp
from routes.damage import bp as damage_bp
from routes.invoices import bp as invoices_bp
from routes.maintenance import bp as maintenance_bp
from routes.allocations import bp as allocations_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = [
    buildings_bp, rooms_bp, groups_bp, participants_bp, stays_bp, turns_bp,
    screenings_bp, linen_bp, keys_bp, damage_bp, invoices_bp, maintenance_bp,
    allocations_bp, clock_bp,
]
