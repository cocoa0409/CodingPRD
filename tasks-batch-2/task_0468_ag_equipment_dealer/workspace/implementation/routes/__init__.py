"""Route registration. Each resource group registers its blueprint."""


def register_routes(app):
    from routes import (
        units,
        floor_plan_notes,
        customers,
        trade_ins,
        deals,
        auctions,
        parts,
        work_orders,
        warranty_claims,
        whole_goods_orders,
        clock_admin,
    )

    units.register(app)
    floor_plan_notes.register(app)
    customers.register(app)
    trade_ins.register(app)
    deals.register(app)
    auctions.register(app)
    parts.register(app)
    work_orders.register(app)
    warranty_claims.register(app)
    whole_goods_orders.register(app)
    clock_admin.register(app)
