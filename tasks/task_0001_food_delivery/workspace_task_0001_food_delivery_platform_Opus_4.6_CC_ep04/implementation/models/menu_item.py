from models.base import VersionedModel


class MenuItem(VersionedModel):
    def __init__(self, restaurant_id, name, price_cents, is_listed=True):
        super().__init__()
        self.restaurant_id = restaurant_id
        self.name = name
        self.price_cents = price_cents
        self.is_listed = is_listed

    def to_dict(self):
        d = self.base_dict()
        d.update({
            "restaurant_id": self.restaurant_id,
            "name": self.name,
            "price_cents": self.price_cents,
            "is_listed": self.is_listed,
        })
        return d
