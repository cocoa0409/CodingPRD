"""Deposit ledger service (PRD §2.10, §3.7).

Maintains the three running totals on Student and appends DepositTransaction
events. amount_cents is always a positive magnitude; txn_type fixes the sign.

Invariants after every settlement:
  deposit_balance_cents  = sum(DEPOSIT) - sum(HOLD) + sum(RELEASE) - sum(CONSUME)
  deposit_held_cents     = sum(HOLD) - sum(RELEASE)
  deposit_consumed_cents = sum(CONSUME)
"""

from db import db, new_lean, touch


def _record_txn(student_id, txn_type, amount_cents, booking_id=None,
                flight_log_id=None, memo=None):
    txn = new_lean()
    txn.update({
        "student_id": student_id,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "booking_id": booking_id,
        "flight_log_id": flight_log_id,
        "memo": memo,
    })
    db.deposit_transactions[txn["id"]] = txn
    return txn


def deposit(student, amount_cents, memo=None):
    """DEPOSIT: add block-time funds. balance += amount."""
    txn = _record_txn(student["id"], "DEPOSIT", amount_cents, memo=memo)
    student["deposit_balance_cents"] += amount_cents
    touch(student)
    return txn


def hold(student, amount_cents, booking_id):
    """HOLD (provisional, at booking confirm). held += amount; balance -= amount."""
    _record_txn(student["id"], "HOLD", amount_cents, booking_id=booking_id)
    student["deposit_held_cents"] += amount_cents
    student["deposit_balance_cents"] -= amount_cents
    touch(student)


def release(student, amount_cents, booking_id):
    """RELEASE (cancel / no-show / part of final settle). held -= ; balance += ."""
    _record_txn(student["id"], "RELEASE", amount_cents, booking_id=booking_id)
    student["deposit_held_cents"] -= amount_cents
    student["deposit_balance_cents"] += amount_cents
    touch(student)


def consume(student, amount_cents, booking_id, flight_log_id):
    """CONSUME (final, at flight-log post). consumed += amount; balance -= amount.

    Note: the net balance adjustment for a final settlement (estimate - actual)
    is realized by calling release(estimate) then consume(actual): release adds
    the estimate back to balance, consume subtracts the actual, leaving the
    documented net (estimate - actual) change.
    """
    _record_txn(student["id"], "CONSUME", amount_cents,
                booking_id=booking_id, flight_log_id=flight_log_id)
    student["deposit_consumed_cents"] += amount_cents
    student["deposit_balance_cents"] -= amount_cents
    touch(student)
