"""Run all self-tests."""
import sys


def main() -> int:
    # Imports register their tests with the harness via the @test decorator.
    from . import (
        test_envelope_and_auth,
        test_restaurants,
        test_riders_customers,
        test_orders,
        test_dispatch_delivery,
        test_returns_fines_workorders,
        test_clock_misc,
    )
    from .harness import run_all

    filter_substr = sys.argv[1] if len(sys.argv) > 1 else None
    return run_all(filter_substr)


if __name__ == "__main__":
    sys.exit(main())
