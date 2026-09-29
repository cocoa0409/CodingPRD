"""Blueprint registry."""

from routes import (
    agreements,
    bookings,
    channels,
    closing,
    financing,
    galleries,
    ops,
    presentations,
    prospects,
    rescission,
    retraining,
)

ALL_BLUEPRINTS = (
    channels.bp,
    galleries.bp,
    prospects.bp,
    bookings.bp,
    presentations.bp,
    agreements.bp,
    financing.bp,
    rescission.bp,
    closing.bp,
    retraining.bp,
    ops.bp,
)
