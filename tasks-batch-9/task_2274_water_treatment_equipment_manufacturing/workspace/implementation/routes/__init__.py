"""Blueprint registry."""
from routes.system import bp as system_bp
from routes.catalogs import bp as catalogs_bp
from routes.projects import bp as projects_bp
from routes.packages import bp as packages_bp
from routes.fat import bp as fat_bp
from routes.orequal import bp as orequal_bp
from routes.demos import bp as demos_bp
from routes.service import bp as service_bp

BLUEPRINTS = (
    system_bp,
    catalogs_bp,
    projects_bp,
    packages_bp,
    fat_bp,
    orequal_bp,
    demos_bp,
    service_bp,
)
