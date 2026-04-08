import sqlite3
import threading

_local = threading.local()
DB_PATH = "/tmp/ecommerce.db"


def get_db():
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return _local.conn


def close_db(e=None):
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()


SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
    id TEXT PRIMARY KEY,
    shop_name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    description TEXT DEFAULT '',
    discount_strategy TEXT NOT NULL DEFAULT 'PERCENTAGE_FIRST',
    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
    monthly_gmv REAL DEFAULT 0,
    settlement_balance REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    base_price REAL NOT NULL,
    inventory_count INTEGER NOT NULL DEFAULT 0,
    reserved_count INTEGER NOT NULL DEFAULT 0,
    available_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS promotions (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    promo_name TEXT NOT NULL,
    promo_type TEXT NOT NULL,
    promo_value REAL NOT NULL,
    promo_threshold REAL DEFAULT 0,
    max_discount_cap REAL,
    stackable INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    max_usage INTEGER,
    usage_count INTEGER NOT NULL DEFAULT 0,
    applicable_categories TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    shipping_address TEXT NOT NULL DEFAULT '',
    subtotal REAL NOT NULL DEFAULT 0,
    discount_amount REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    payment_status TEXT NOT NULL DEFAULT 'UNPAID',
    fulfillment_status TEXT NOT NULL DEFAULT 'PENDING',
    order_status TEXT NOT NULL DEFAULT 'CREATED',
    reservation_expires_at TEXT,
    applied_promotions TEXT NOT NULL DEFAULT '[]',
    commission_amount REAL DEFAULT 0,
    commission_rate REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    product_snapshot TEXT NOT NULL DEFAULT '{}',
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    line_total REAL NOT NULL,
    discount_share REAL NOT NULL DEFAULT 0,
    final_price REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    payment_type TEXT NOT NULL,
    payment_method TEXT,
    transaction_ref TEXT,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    refund_type TEXT NOT NULL,
    refund_items TEXT NOT NULL DEFAULT '[]',
    refund_amount REAL DEFAULT 0,
    refund_subtotal REAL DEFAULT 0,
    refund_discount_share REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    inventory_restored INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    gross_amount REAL NOT NULL DEFAULT 0,
    total_commission REAL NOT NULL DEFAULT 0,
    total_refunds REAL NOT NULL DEFAULT 0,
    net_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shop_id) REFERENCES shops(id)
);
"""
