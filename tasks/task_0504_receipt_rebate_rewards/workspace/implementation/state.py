"""Holds the single in-memory Store instance for the process.

The store is created once at import time and starts completely empty. No entities
are ever seeded here — every entity is constructed by callers via the API.
"""
from db import Store

store = Store()
