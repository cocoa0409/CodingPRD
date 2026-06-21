"""Customer ownership resolution (PRD §2.1).

A Customer may read/act only on their own PrintFile, Order, OrderLine,
PrintRun, and Shipment. Staff roles (BureauAdmin/Operator/QAReviewer) have read
access across the whole bureau.

Ownership for nested work entities is resolved transitively through the owning
order's customer_id.
"""

from db import DB


def order_customer_id(order):
    return order["customer_id"]


def line_customer_id(line):
    order = DB.orders.get(line["order_id"])
    return order["customer_id"] if order else None


def run_customer_id(run):
    line = DB.order_lines.get(run["order_line_id"])
    if not line:
        return None
    return line_customer_id(line)


def shipment_customer_id(shipment):
    order = DB.orders.get(shipment["order_id"])
    return order["customer_id"] if order else None


def file_customer_id(print_file):
    return print_file["customer_id"]
