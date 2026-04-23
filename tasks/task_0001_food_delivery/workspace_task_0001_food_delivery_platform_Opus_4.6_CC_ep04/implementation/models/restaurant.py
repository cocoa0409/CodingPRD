from models.base import VersionedModel, format_ts


class Restaurant(VersionedModel):
    def __init__(self, name, address, lat, lng, commission_rate_override=None):
        super().__init__()
        self.name = name
        self.address = address
        self.lat = lat
        self.lng = lng
        self.status = "PENDING_APPROVAL"
        self.commission_rate_override = commission_rate_override
        self.pending_settlement_cents = 0

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "name": self.name,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "status": self.status,
            "commission_rate_override": self.commission_rate_override,
            "pending_settlement_cents": self.pending_settlement_cents,
        })
        return d
