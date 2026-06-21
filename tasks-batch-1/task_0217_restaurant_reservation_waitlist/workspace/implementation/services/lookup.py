"""Entity lookup helpers with not-found semantics (PRD §2.8)."""
import db
from errors import err, ERR_NOT_FOUND


def get_or_404(collection, entity_id):
    rec = collection.get(entity_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "resource not found")
    return rec


def restaurant_of_table(table):
    area = db.dining_areas.get(table["dining_area_id"])
    if area is None:
        return None
    return db.restaurants.get(area["restaurant_id"])
