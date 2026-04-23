from models.base import SimpleModel, format_ts


class Assignment(SimpleModel):
    def __init__(self, order_id, rider_id):
        super().__init__()
        self.order_id = order_id
        self.rider_id = rider_id
        self.route_group_id = None
        self.status = "OFFERED"
        self.offered_at = self.created_at
        self.accepted_at = None
        self.picked_up_at = None
        self.delivered_at = None
        self.final_delivery_fee_cents = None

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "order_id": self.order_id,
            "rider_id": self.rider_id,
            "route_group_id": self.route_group_id,
            "status": self.status,
            "offered_at": format_ts(self.offered_at),
            "accepted_at": format_ts(self.accepted_at) if self.accepted_at else None,
            "picked_up_at": format_ts(self.picked_up_at) if self.picked_up_at else None,
            "delivered_at": format_ts(self.delivered_at) if self.delivered_at else None,
            "final_delivery_fee_cents": self.final_delivery_fee_cents,
        })
        return d
