"""Entry point for the Onboarding I-9 & E-Verify API."""
import os
from app import create_app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application = create_app()
    application.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=False)
