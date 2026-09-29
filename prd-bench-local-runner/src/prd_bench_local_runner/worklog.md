
## Step 9: Complete PRD — 2026-09-02T00:18:00.000Z

`workspace/PRD_COMPLETED.md` is written: a minimal in-place patch over `PRD_FINALIZED.md`, no new sections, no new paragraphs, no lines added or removed.

**Stats**
- PRD_FINALIZED.md: 476 lines / 107,415 chars → PRD_COMPLETED.md: 476 lines / 115,149 chars (**char delta +7,679**)
- 31 paragraphs revised in place: **24 ambiguity-pins**, **8 mismatch-revisions** (§3.7's environment paragraph carries one of each)

**Changes** (impl paths relative to `workspace/implementation/`)
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-alnum chars — response.py:12-13
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the host wall clock, not the logical clock — response.py:16-18
- §2.3 — revise — ambiguity — `created_at` ties broken by creation sequence; `total_count` is post-filter/pre-page; `has_more` = offset+returned < total_count — db.py:154-155, response.py:35
- §2.3 — revise — ambiguity — an out-of-set filter value matches nothing rather than 400; `direction` other than `INCOMING` means `OUTGOING` — changes.py:136, flags.py:66-69
- §2.5 — revise — ambiguity — `version` is 1 on creation — db.py:113
- §2.6 — revise — ambiguity — computed fractional values render as plain integers when integral; client-supplied percentages echo verbatim — db.py:91-99
- §2.7 — revise — **mismatch** — planning does *not* supersede a still-`PLANNED` rung; the new step just takes the next `step_index` — flags.py:127-141
- §2.8 r3 — revise — ambiguity — absent/empty body = `{}`; `null` on an optional input = omitted (default applies), `null` on a required input = missing; undeclared fields ignored — validate.py:15-31
- §2.8 r9 — revise — **mismatch** — soak-start's flag-`state` check belongs to rank 9, evaluated before the linked-change check and thus before ownership — flags.py:172-190
- §2.10 — revise — ambiguity — a re-write that changes nothing is not a mutation (no `updated_at`/`version` move); one hop = one version bump however many fields — db.py:126-136
- §3.1 — revise — ambiguity — train `name` at most 80 characters — trains.py:22
- §3.2 — revise — **mismatch** — `readiness_score_projected` has no phase gate; even a `ROLLED_BACK` release recomputes on its triggers — changes.py:376-379
- §3.2 — revise — ambiguity — freeze-exception `justification` non-empty and unstored; a repeat grant is wholly inert (no count, no version) — releases.py:120-130
- §3.3 — revise — ambiguity — authoring a change is permitted in any release `phase` — releases.py:133-150
- §3.3 — revise — ambiguity — flag-linking checks no change/flag state and permits duplicate pairs — changes.py:149-168
- §3.4 — revise — **mismatch** — merge unblocks dependents *before* recomputing `rollback_plan_confirmed` and `readiness_score_projected` (one release mutation, blocked penalty already gone) — changes.py:344-350
- §3.4 — revise — ambiguity — withdrawal `reason` validated but not stored — changes.py:358
- §3.5 — revise — ambiguity — `soak_minutes` whole minutes ≥ 0; planning has no flag-`state` gate (incl. `ARCHIVED`) — flags.py:88-96
- §3.5 — revise — **mismatch** — start-soak precondition order pinned to impl (step → flag state → linked changes → ownership → cleanup → soaking → index → deployment) — flags.py:172-208
- §3.5 — revise — **mismatch** — apply order (flag state before ownership); apply recomputes `stale_debt_points` **and** `cleanup_state` in one mutation, stamps no `last_sweep_at`, never pauses/voids/recomputes readiness; exposure 100 is the integer 100 — flags.py:228-262
- §3.5 — revise — ambiguity — pause `reason` not persisted — flags.py:272-277
- §3.5 — revise — ambiguity — archival leaves `kill_switch_engaged`, `current_exposure_pct` and any `SOAKING` step untouched — flags.py:314-323
- §3.6 — revise — ambiguity — "affected flag" = one the sweep actually altered or paused; a repeat sweep at an unchanged clock recomputes no release — cascade.py:357-389
- §3.7 — revise — **mismatch** + ambiguity — `last_deployment_end_at` recomputed only on completion or deployment rollback (reservation and abort leave it); a blackout needs *both* endpoints — deployments.py:296, cascade.py:292, deployments.py:136
- §3.7 — revise — ambiguity — `abort_error_rate_pct` any number > 0, `abort_latency_p95_ms` whole ms ≥ 1 — deployments.py:44-45
- §3.7 — revise — ambiguity — sample `latency_p95_ms` whole ms; ingestion has no delivery-state precondition — deployments.py:148-179
- §3.7 — revise — ambiguity — canary analysis has no delivery-state or strategy precondition — deployments.py:196-206
- §3.7 — revise — ambiguity — `min_sample_count` 0 with no qualifying rows yields `PASS` / score 100 — calc.py:239-286
- §3.7 — revise — ambiguity — an `abort_triggered` verdict outside `IN_PROGRESS`/`CANARY_SOAK` still writes verdict, `verification_state` and `health_score` but runs no hop — deployments.py:229-239
- §3.7 — revise — ambiguity — deployment-rollback `reason` not persisted — deployments.py:306-307
- §3.9 — revise — ambiguity — `missing_items` in canonical item order; `waivers` in record order — calc.py:529-535
- §3.9 — revise — **mismatch** — waiver `justification` non-empty; `base_index` and item satisfaction come from the packet's stored snapshot (assembly, or a release-notes publication refresh), never recomputed live at waiver time — docs.py:137-159

Not changed (verified already uniquely pinned): the 50-error catalogue and its statuses, rank-4/5/6/7 not-found + uniqueness + concurrency wiring, all eight calculations (risk score, both readiness variants, canary verdict, stale debt, ladder geometry, note generation, linkage, completeness index), the freeze/unfreeze, cut, abort, rollback and sweep cascade hop orders, and §2.4 timestamp rendering.
