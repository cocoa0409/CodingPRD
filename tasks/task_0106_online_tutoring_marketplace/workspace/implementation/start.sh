#!/bin/bash
set -e
pip install -q -r requirements.txt
exec python app.py
