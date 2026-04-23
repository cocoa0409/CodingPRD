from models.base import VersionedModel, format_ts


class Order(VersionedModel):
    def __init__(self, customer_id, restaurant_id, items, subtotal_cents,
                 distance_km, is_peak, promised_delivery_time,
                 provisional_delivery_fee_cents, provisional_commission_cents):
        super().__init__()
        self.customer_id = customer_id
        self.restaurant_id = restaurant_id
        self.items = items
        self.subtotal_cents = subtotal_cents
        self.distance_km = distance_km
        self.is_peak = is_peak
        self.promised_delivery_time = promised_delivery_time
        self.provisional_delivery_fee_cents = provisional_delivery_fee_cents
        self.provisional_commission_cents = provisional_commission_cents
        self.final_delivery_fee_cents = None
        self.final_commission_cents = None
        self.actual_delivery_time = None
        self.minutes_late = None
        self.status = "PLACED"
        self.payment_status = "AUTHORIZED"

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "customer_id": self.customer_id,
            "restaurant_id": self.restaurant_id,
            "items": self.items,
            "subtotal_cents": self.subtotal_cents,
            "distance_km": self.distance_km,
            "is_peak": self.is_peak,
            "promised_delivery_time": format_ts(self.promised_delivery_time),
            "provisional_delivery_fee_cents": self.provisional_delivery_fee_cents,
            "provisional_commission_cents": self.provisional_commission_cents,
            "final_delivery_fee_cents": self.final_delivery_fee_cents,
            "final_commission_cents": self.final_commission_cents,
            "actual_delivery_time": format_ts(self.actual_delivery_time) if self.actual_delivery_time else None,
            "minutes_late": self.minutes_late,
            "status": self.status,
            "payment_status": self.payment_status,
        })
        return d
