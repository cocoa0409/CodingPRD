from models.base import VersionedModel


class Customer(VersionedModel):
    def __init__(self, name, phone, address, lat, lng):
        super().__init__()
        self.name = name
        self.phone = phone
        self.address = address
        self.lat = lat
        self.lng = lng
        self.credit_balance_cents = 0
        self.trust_score = 1.0

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "name": self.name,
            "phone": self.phone,
            "address": self.address,
            "lat": self.lat,
            "lng": self.lng,
            "credit_balance_cents": self.credit_balance_cents,
            "trust_score": self.trust_score,
        })
        return d
