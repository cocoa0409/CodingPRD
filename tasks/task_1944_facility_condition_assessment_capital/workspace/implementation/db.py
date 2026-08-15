"""In-memory data store. Dicts keyed by id; starts empty on every boot.

No seeding, no disk persistence — every start.sh re-invocation wipes state.
"""

clients = {}
facilities = {}
asset_systems = {}
deficiencies = {}
capital_plans = {}
funding_scenarios = {}
plan_line_items = {}
project_bundles = {}
refresh_cycles = {}
condition_snapshots = {}
