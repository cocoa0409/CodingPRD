import uuid
from flask_sqlalchemy import SQLAlchemy
from utils.clock import clock

db = SQLAlchemy()


def gen_uuid():
    return str(uuid.uuid4())


def now_str():
    return clock.format(clock.now())


class Restaurant(db.Model):
    __tablename__ = 'restaurants'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String, nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    status = db.Column(db.String, nullable=False, default='PENDING_APPROVAL')
    commission_rate_override = db.Column(db.Float, nullable=True)
    pending_settlement_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.String, nullable=False, default=now_str)
    updated_at = db.Column(db.String, nullable=False, default=now_str)
    version = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
            'lat': self.lat,
            'lng': self.lng,
            'status': self.status,
            'commission_rate_override': self.commission_rate_override,
            'pending_settlement_cents': self.pending_settlement_cents,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
        }

    def touch(self):
        self.updated_at = now_str()
        self.version += 1


class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    restaurant_id = db.Column(db.String, db.ForeignKey('restaurants.id'), nullable=False)
    name = db.Column(db.String, nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    is_listed = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.String, nullable=False, default=now_str)
    updated_at = db.Column(db.String, nullable=False, default=now_str)
    version = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        return {
            'id': self.id,
            'restaurant_id': self.restaurant_id,
            'name': self.name,
            'price_cents': self.price_cents,
            'is_listed': self.is_listed,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
        }

    def touch(self):
        self.updated_at = now_str()
        self.version += 1


class Rider(db.Model):
    __tablename__ = 'riders'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    name = db.Column(db.String, nullable=False)
    phone = db.Column(db.String, nullable=False, unique=True)
    status = db.Column(db.String, nullable=False, default='OFFLINE')
    on_time_rate = db.Column(db.Float, nullable=False, default=1.0)
    acceptance_rate = db.Column(db.Float, nullable=False, default=1.0)
    rating = db.Column(db.Float, nullable=False, default=5.0)
    bonus_tier = db.Column(db.String, nullable=False, default='BRONZE')
    wallet_balance_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.String, nullable=False, default=now_str)
    updated_at = db.Column(db.String, nullable=False, default=now_str)
    version = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'status': self.status,
            'on_time_rate': self.on_time_rate,
            'acceptance_rate': self.acceptance_rate,
            'rating': self.rating,
            'bonus_tier': self.bonus_tier,
            'wallet_balance_cents': self.wallet_balance_cents,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
        }

    def touch(self):
        self.updated_at = now_str()
        self.version += 1


class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    name = db.Column(db.String, nullable=False)
    phone = db.Column(db.String, nullable=False, unique=True)
    address = db.Column(db.String, nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    credit_balance_cents = db.Column(db.Integer, nullable=False, default=0)
    trust_score = db.Column(db.Float, nullable=False, default=1.0)
    created_at = db.Column(db.String, nullable=False, default=now_str)
    updated_at = db.Column(db.String, nullable=False, default=now_str)
    version = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'address': self.address,
            'lat': self.lat,
            'lng': self.lng,
            'credit_balance_cents': self.credit_balance_cents,
            'trust_score': self.trust_score,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
        }

    def touch(self):
        self.updated_at = now_str()
        self.version += 1


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    customer_id = db.Column(db.String, db.ForeignKey('customers.id'), nullable=False)
    restaurant_id = db.Column(db.String, db.ForeignKey('restaurants.id'), nullable=False)
    status = db.Column(db.String, nullable=False, default='PLACED')
    payment_status = db.Column(db.String, nullable=False, default='UNPAID')
    items = db.Column(db.JSON, nullable=False)
    subtotal_cents = db.Column(db.Integer, nullable=False)
    distance_km = db.Column(db.Float, nullable=False)
    is_peak = db.Column(db.Boolean, nullable=False)
    promised_delivery_time = db.Column(db.String, nullable=True)
    actual_delivery_time = db.Column(db.String, nullable=True)
    minutes_late = db.Column(db.Integer, nullable=True)
    provisional_delivery_fee_cents = db.Column(db.Integer, nullable=False)
    final_delivery_fee_cents = db.Column(db.Integer, nullable=True)
    provisional_commission_cents = db.Column(db.Integer, nullable=False)
    final_commission_cents = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.String, nullable=False, default=now_str)
    updated_at = db.Column(db.String, nullable=False, default=now_str)
    version = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'restaurant_id': self.restaurant_id,
            'status': self.status,
            'payment_status': self.payment_status,
            'items': self.items,
            'subtotal_cents': self.subtotal_cents,
            'distance_km': self.distance_km,
            'is_peak': self.is_peak,
            'promised_delivery_time': self.promised_delivery_time,
            'actual_delivery_time': self.actual_delivery_time,
            'minutes_late': self.minutes_late,
            'provisional_delivery_fee_cents': self.provisional_delivery_fee_cents,
            'final_delivery_fee_cents': self.final_delivery_fee_cents,
            'provisional_commission_cents': self.provisional_commission_cents,
            'final_commission_cents': self.final_commission_cents,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
        }

    def touch(self):
        self.updated_at = now_str()
        self.version += 1


class Assignment(db.Model):
    __tablename__ = 'assignments'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    order_id = db.Column(db.String, db.ForeignKey('orders.id'), nullable=False)
    rider_id = db.Column(db.String, db.ForeignKey('riders.id'), nullable=False)
    status = db.Column(db.String, nullable=False, default='OFFERED')
    route_group_id = db.Column(db.String, db.ForeignKey('route_groups.id'), nullable=True)
    offered_at = db.Column(db.String, nullable=False, default=now_str)
    accepted_at = db.Column(db.String, nullable=True)
    picked_up_at = db.Column(db.String, nullable=True)
    delivered_at = db.Column(db.String, nullable=True)
    final_delivery_fee_cents = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.String, nullable=False, default=now_str)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'rider_id': self.rider_id,
            'status': self.status,
            'route_group_id': self.route_group_id,
            'offered_at': self.offered_at,
            'accepted_at': self.accepted_at,
            'picked_up_at': self.picked_up_at,
            'delivered_at': self.delivered_at,
            'final_delivery_fee_cents': self.final_delivery_fee_cents,
            'created_at': self.created_at,
        }


class RouteGroup(db.Model):
    __tablename__ = 'route_groups'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    rider_id = db.Column(db.String, db.ForeignKey('riders.id'), nullable=False)
    assignment_ids = db.Column(db.JSON, nullable=False, default=list)
    merged_at = db.Column(db.String, nullable=False, default=now_str)
    status = db.Column(db.String, nullable=False, default='ACTIVE')
    created_at = db.Column(db.String, nullable=False, default=now_str)

    def to_dict(self):
        return {
            'id': self.id,
            'rider_id': self.rider_id,
            'assignment_ids': self.assignment_ids,
            'merged_at': self.merged_at,
            'status': self.status,
            'created_at': self.created_at,
        }


class Return(db.Model):
    __tablename__ = 'returns'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    order_id = db.Column(db.String, db.ForeignKey('orders.id'), nullable=False)
    reason = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False, default='REQUESTED')
    requested_refund_cents = db.Column(db.Integer, nullable=False)
    approved_refund_cents = db.Column(db.Integer, nullable=True)
    reviewer_cs_user_id = db.Column(db.String, nullable=True)
    created_at = db.Column(db.String, nullable=False, default=now_str)
    updated_at = db.Column(db.String, nullable=False, default=now_str)
    version = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'reason': self.reason,
            'status': self.status,
            'requested_refund_cents': self.requested_refund_cents,
            'approved_refund_cents': self.approved_refund_cents,
            'reviewer_cs_user_id': self.reviewer_cs_user_id,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
        }

    def touch(self):
        self.updated_at = now_str()
        self.version += 1


class Fine(db.Model):
    __tablename__ = 'fines'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    subject_type = db.Column(db.String, nullable=False)
    subject_id = db.Column(db.String, nullable=False)
    reason = db.Column(db.String, nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    settlement_status = db.Column(db.String, nullable=False, default='PENDING')
    order_id = db.Column(db.String, nullable=True)
    created_at = db.Column(db.String, nullable=False, default=now_str)

    def to_dict(self):
        return {
            'id': self.id,
            'subject_type': self.subject_type,
            'subject_id': self.subject_id,
            'reason': self.reason,
            'amount_cents': self.amount_cents,
            'settlement_status': self.settlement_status,
            'order_id': self.order_id,
            'created_at': self.created_at,
        }


class WorkOrder(db.Model):
    __tablename__ = 'work_orders'
    id = db.Column(db.String, primary_key=True, default=gen_uuid)
    opened_by_role = db.Column(db.String, nullable=False)
    opened_by_id = db.Column(db.String, nullable=False)
    category = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False, default='OPEN')
    related_order_id = db.Column(db.String, nullable=True)
    related_return_id = db.Column(db.String, nullable=True)
    assigned_cs_user_id = db.Column(db.String, nullable=True)
    resolution_notes = db.Column(db.String, nullable=True)
    created_at = db.Column(db.String, nullable=False, default=now_str)
    updated_at = db.Column(db.String, nullable=False, default=now_str)
    version = db.Column(db.Integer, nullable=False, default=1)

    def to_dict(self):
        return {
            'id': self.id,
            'opened_by_role': self.opened_by_role,
            'opened_by_id': self.opened_by_id,
            'category': self.category,
            'status': self.status,
            'related_order_id': self.related_order_id,
            'related_return_id': self.related_return_id,
            'assigned_cs_user_id': self.assigned_cs_user_id,
            'resolution_notes': self.resolution_notes,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
        }

    def touch(self):
        self.updated_at = now_str()
        self.version += 1
