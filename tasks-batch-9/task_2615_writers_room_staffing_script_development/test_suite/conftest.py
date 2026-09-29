"""Shared pytest fixtures for the writers-room staffing and script development suite.

The harness restarts the server and empties its store before every individual
test, so every state fixture below builds its world from scratch through the
public endpoints. Only the client itself is shared across the session.
"""

from test_helpers.fixtures import (  # noqa: F401
    active_room_world,
    agreement,
    api,
    approved_assignment_world,
    arbitration_world,
    assignment_world,
    cleared_world,
    clearance_world,
    closed_credit_world,
    deadlocked_world,
    delivered_assignment_world,
    episode_world,
    locked_episode_world,
    offered_seat_world,
    registry,
    season_world,
    staffing_room_world,
    submissions_world,
    voted_world,
    wrapped_room_world,
)
