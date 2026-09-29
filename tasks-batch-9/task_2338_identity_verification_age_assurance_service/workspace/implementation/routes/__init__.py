"""Route blueprints."""
from . import attempts, bias, clients, ops, pathways, policies, reviews, sessions

BLUEPRINTS = (
    clients.bp,
    policies.bp,
    sessions.bp,
    attempts.bp,
    pathways.bp,
    reviews.bp,
    bias.bp,
    ops.bp,
)
