"""In-memory data store keyed by id."""
from threading import RLock

LOCK = RLock()

members = {}             # id -> Member dict
subscriptions = {}       # id -> Subscription dict
payment_attempts = {}    # id -> PaymentAttempt dict
stores = {}              # id -> Store dict
class_sessions = {}      # id -> ClassSession dict
trainers = {}            # id -> Trainer dict
equipment_pools = {}     # id -> EquipmentPool dict
bookings = {}            # id -> Booking dict
coupons = {}             # id -> Coupon dict
referrals = {}           # id -> ReferralReward dict


def reset_all():
    members.clear()
    subscriptions.clear()
    payment_attempts.clear()
    stores.clear()
    class_sessions.clear()
    trainers.clear()
    equipment_pools.clear()
    bookings.clear()
    coupons.clear()
    referrals.clear()
