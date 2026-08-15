from flask import Blueprint


def make_blueprint(name):
    # Flat topology: every endpoint is mounted at the service root "/".
    return Blueprint(name, __name__)
