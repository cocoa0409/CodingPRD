from models.base import VersionedModel, format_ts


class Rider(VersionedModel):
    def __init__(self, name, phone):
        super().__init__()
        self.name = name
        self.phone = phone
        self.status = "OFFLINE"
        self.on_time_rate = 1.0
        self.acceptance_rate = 1.0
        self.rating = 5.0
        self.wallet_balance_cents = 0
        self.bonus_tier = "BRONZE"

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "name": self.name,
            "phone": self.phone,
            "status": self.status,
            "on_time_rate": self.on_time_rate,
            "acceptance_rate": self.acceptance_rate,
            "rating": self.rating,
            "wallet_balance_cents": self.wallet_balance_cents,
            "bonus_tier": self.bonus_tier,
        })
        return d
