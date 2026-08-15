def register_routes(app):
    from . import (
        commercial,
        equipment,
        ops,
        orders,
        practices,
        products,
        service,
        usage_profiles,
    )

    for module in (
        practices,
        products,
        usage_profiles,
        orders,
        ops,
        equipment,
        service,
        commercial,
    ):
        app.register_blueprint(module.bp, url_prefix="/api")
