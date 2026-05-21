"""Service-layer modules grouped by business concern.

- workweeks: workweek upsert, week-anchor checks, pay-engine orchestration
- shifts: shift lifecycle, punch processing, detention/meal recompute
- time_edits: time-edit lifecycle (submit/approve/reject/revert) + cascade
- tips: tip-declaration mutation + shortfall computation
- employees: validation of tipped-field consistency, wage floor checks
"""
