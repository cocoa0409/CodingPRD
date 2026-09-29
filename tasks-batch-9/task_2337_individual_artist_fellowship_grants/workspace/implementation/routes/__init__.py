from routes.core import bp as core_bp
from routes.applications import bp as applications_bp
from routes.panels import bp as panels_bp
from routes.awards import bp as awards_bp
from routes.reports import bp as reports_bp

blueprints = (core_bp, applications_bp, panels_bp, awards_bp, reports_bp)
