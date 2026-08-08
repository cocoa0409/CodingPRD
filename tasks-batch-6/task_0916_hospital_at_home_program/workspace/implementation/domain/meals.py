"""MealPlan lifecycle. Every one of the four moves is performed by the system
rather than by an operator (PRD 3.7)."""

import derived
import store


def suspend_active_plans(episode_id):
    """Bed return: each ACTIVE plan suspends and permanently forfeits one day."""
    for plan in derived.episode_meal_plans(episode_id):
        if plan["status"] != "ACTIVE":
            continue
        plan["status"] = "SUSPENDED"
        plan["suspension_day_count"] = plan["suspension_day_count"] + 1
        store.touch(plan)


def resume_suspended_plans(episode_id):
    """Readmission: each SUSPENDED plan returns to ACTIVE (the forfeited day stays lost)."""
    for plan in derived.episode_meal_plans(episode_id):
        if plan["status"] != "SUSPENDED":
            continue
        plan["status"] = "ACTIVE"
        store.touch(plan)


def end_plans_on_discharge(episode_id):
    """ACTIVE plans complete; plans still SUSPENDED at discharge cancel."""
    for plan in derived.episode_meal_plans(episode_id):
        if plan["status"] == "ACTIVE":
            plan["status"] = "COMPLETED"
            store.touch(plan)
        elif plan["status"] == "SUSPENDED":
            plan["status"] = "CANCELLED"
            store.touch(plan)
