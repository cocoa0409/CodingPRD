"""Shared pytest configuration for the Nurse Triage Call Center suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import api, fresh_clock, world  # noqa: E402,F401

__all__ = ["api", "world", "fresh_clock"]
